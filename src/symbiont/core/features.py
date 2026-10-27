"""Situation -> 86 numbers, the one input every Decider reads.

The layout is fixed so the count holds (the mushroom body expects 86 inputs):
6 position, 6 action kind, 18 file history, 24 signal history, 8 command
family, 8 outcome trail, 2 lines added, 14 hashed command tokens.

FEATURE_NAMES labels the columns for the dashboard. It is never shown to a
model: notes are written in domain prose, not in feature names or scores.
"""

import math
import re
import zlib
from collections.abc import Sequence

import numpy as np

from symbiont.core.slot import Situation
from symbiont.miner.commands import normalise_command
from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.records.schema import Kind, Record

# Step-count buckets for position: records seen so far in the session.
_POSITION_EDGES = (5, 10, 20, 40, 80)
# Touch-count buckets for file history: 0, 1, 2, 3-4, 5-8, 9+.
_COUNT_EDGES = (1, 2, 3, 5, 9)
_ACTIONS = ("command", "read", "edit", "agent_turn", "user_turn", "other")
_FILE_COUNTS = ("edits", "reads", "failures")
_SIGNALS = tuple(Signal)
_RECENCY = ("recent", "earlier", "other_here", "other_elsewhere")
_RECENT_STEPS = 10
_FAMILIES = ("tests", "python", "git", "search", "view", "install", "build", "other")
_PROGRAMS_OF_FAMILY = {
    "tests": ("pytest", "tox", "nox", "unittest"),
    "python": ("python", "python3"),
    "git": ("git",),
    "search": ("grep", "egrep", "rg", "ag", "find", "ls"),
    "view": ("cat", "head", "tail", "sed", "less"),
    "install": ("pip", "uv", "npm", "poetry", "conda"),
    "build": ("make", "cmake", "cargo", "go"),
}
_FAMILY_OF = {
    program: family for family, programs in _PROGRAMS_OF_FAMILY.items() for program in programs
}
_TRAIL = 8
_TOKENS = 14
_WORD = re.compile(r"\w+")

FEATURE_NAMES: tuple[str, ...] = (
    *(f"position_{i}" for i in range(len(_POSITION_EDGES) + 1)),
    *(f"action_{a}" for a in _ACTIONS),
    *(f"file_{c}_{b}" for c in _FILE_COUNTS for b in range(len(_COUNT_EDGES) + 1)),
    *(f"signal_{s.value}_{r}" for s in _SIGNALS for r in _RECENCY),
    *(f"family_{f}" for f in _FAMILIES),
    *(f"trail_{i}" for i in range(_TRAIL)),
    "lines_added_step",
    "lines_added_session",
    *(f"token_{i}" for i in range(_TOKENS)),
)
N_FEATURES = len(FEATURE_NAMES)

# What the counter learners read (spec 4.2): position, file history, lines
# added and the edit kind. Everything else is for richer learners.
_COUNTER_PREFIXES = ("position_", "file_", "lines_added_")
COUNTER_FEATURES: tuple[int, ...] = tuple(
    i for i, n in enumerate(FEATURE_NAMES) if n.startswith(_COUNTER_PREFIXES) or n == "action_edit"
)

ScratchFile = tuple[str, str]  # (session_id, path)


def featurise(
    situation: Situation,
    *,
    hubs: frozenset[str] = frozenset(),
    scratch: frozenset[ScratchFile] = frozenset(),
) -> np.ndarray:
    """Encode a situation as the fixed-length input vector.

    `hubs`: modules imported by most test files; breaking one says nothing
    about the edit, so blast-radius history whose dependent is one is ignored.
    `scratch`: (session, path) files a session made for itself, beyond those
    visible in this session's own records; reworking them is not a mistake.
    """
    prefix = situation.session_prefix
    current = prefix[-1] if prefix else None
    parts = [
        _position(prefix),
        _action(current),
        _file_history(prefix),
        _signal_history(situation, hubs, scratch | scratch_files(prefix)),
        _command_family(current),
        _outcome_trail(prefix),
        _lines_added(prefix),
        _command_tokens(current),
    ]
    x = np.concatenate(parts).astype(np.float32)
    assert x.shape == (N_FEATURES,)
    return x


def scratch_files(records: Sequence[Record]) -> frozenset[ScratchFile]:
    """Files the records show being created from nothing."""
    return frozenset(
        (r.session_id, path)
        for r in records
        if r.kind == Kind.EDIT and (r.diff or "").startswith("--- /dev/null")
        for path in r.files
    )


def _one_hot(size: int, index: int) -> np.ndarray:
    vector = np.zeros(size)
    vector[index] = 1.0
    return vector


def _bucket(value: int, edges: tuple[int, ...]) -> int:
    return sum(value >= e for e in edges)


def _position(prefix: Sequence[Record]) -> np.ndarray:
    size = len(_POSITION_EDGES) + 1
    return _one_hot(size, _bucket(len(prefix), _POSITION_EDGES)) if prefix else np.zeros(size)


def _action(current: Record | None) -> np.ndarray:
    if current is None:
        return np.zeros(len(_ACTIONS))
    name = current.kind.value
    return _one_hot(len(_ACTIONS), _ACTIONS.index(name if name in _ACTIONS else "other"))


def _file_history(prefix: Sequence[Record]) -> np.ndarray:
    size = len(_COUNT_EDGES) + 1
    if not prefix or not prefix[-1].files:
        return np.zeros(len(_FILE_COUNTS) * size)
    path, earlier = prefix[-1].files[0], prefix[:-1]
    touching = [r for r in earlier if path in r.files]
    counts = (
        sum(r.kind == Kind.EDIT for r in touching),
        sum(r.kind == Kind.READ for r in touching),
        sum(r.exit_code not in (None, 0) for r in touching),
    )
    return np.concatenate([_one_hot(size, _bucket(c, _COUNT_EDGES)) for c in counts])


def _signal_history(
    situation: Situation, hubs: frozenset[str], scratch: frozenset[ScratchFile]
) -> np.ndarray:
    prefix = situation.session_prefix
    current_session = prefix[-1].session_id if prefix else None
    current_step = prefix[-1].step if prefix else 0
    current_path = prefix[-1].files[0] if prefix and prefix[-1].files else None
    counts = np.zeros((len(_SIGNALS), len(_RECENCY)))
    for point in meaningful_history(situation, hubs, scratch):
        if point.session_id == current_session:
            recency = 0 if current_step - point.step <= _RECENT_STEPS else 1
        else:
            recency = 2 if current_path is not None and current_path in point.signature.key else 3
        counts[_SIGNALS.index(point.signature.signal), recency] += 1
    return (np.minimum(counts, 3) / 3).ravel()


def meaningful_history(
    situation: Situation,
    hubs: frozenset[str] = frozenset(),
    scratch: frozenset[ScratchFile] = frozenset(),
) -> list[PainPoint]:
    """Pain points that say something about the current step.

    Strictly before it (a point at or after it would leak the answer) and not
    hub breakage or rework of a file the session made for itself. Every learner
    reads history through this, so they agree on what counts.
    """
    prefix = situation.session_prefix
    current_session = prefix[-1].session_id if prefix else None
    current_step = prefix[-1].step if prefix else 0
    scratch = scratch | scratch_files(prefix)
    return [
        point
        for point in situation.history
        if not _carries_no_signal(point, hubs, scratch)
        and not (point.session_id == current_session and point.step >= current_step)
    ]


def _carries_no_signal(
    point: PainPoint, hubs: frozenset[str], scratch: frozenset[ScratchFile]
) -> bool:
    signal, key = point.signature.signal, point.signature.key
    if signal == Signal.BLAST_RADIUS:
        return key[-1] in hubs
    if signal == Signal.REWORKED_EDIT:
        return (point.session_id, key[0]) in scratch
    return False


def _command_family(current: Record | None) -> np.ndarray:
    vector = np.zeros(len(_FAMILIES))
    if current is not None and current.command:
        program, _ = normalise_command(current.command)
        vector[_FAMILIES.index(_FAMILY_OF.get(program, "other"))] = 1.0
    return vector


def _outcome_trail(prefix: Sequence[Record]) -> np.ndarray:
    codes = [r.exit_code for r in reversed(prefix) if r.exit_code is not None][:_TRAIL]
    vector = np.zeros(_TRAIL)
    vector[: len(codes)] = [float(code != 0) for code in codes]
    return vector


def _added(record: Record) -> int:
    lines = (record.diff or "").splitlines()
    return sum(line.startswith("+") and not line.startswith("+++") for line in lines)


def _lines_added(prefix: Sequence[Record]) -> np.ndarray:
    if not prefix:
        return np.zeros(2)
    applied = [r for r in prefix if r.kind == Kind.EDIT and r.exit_code != 1]
    this_step = _added(prefix[-1]) if prefix[-1] in applied else 0
    return np.array([math.log1p(this_step), math.log1p(sum(map(_added, applied)))])


def _command_tokens(current: Record | None) -> np.ndarray:
    vector = np.zeros(_TOKENS)
    if current is not None and current.command:
        # crc32, not hash(): hash() is salted per process.
        for token in _WORD.findall(current.command):
            vector[zlib.crc32(token.encode()) % _TOKENS] = 1.0
    return vector
