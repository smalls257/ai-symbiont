"""What resolved a pain point, as the steps the history shows.

Shared by lessons (what a note says was done) and Route B (what a model is trained to do), so the
two never disagree about the fix. Finding nothing is an answer with a stated reason, never a
guess. A failed command's fix is what changed before the later pass of the same program,
subcommand and target; re-running it unchanged fixes nothing, and edits to files it never names
are reported alongside.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from symbiont.miner.changes import applied_edit, changes_workspace
from symbiont.miner.commands import normalise_command, program_words
from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.records.schema import Kind, Record

NO_LATER_SUCCESS = (
    "no later command with exit 0 on the same program and target followed the failure"
)
NOTHING_CHANGED = "the same command passed later with nothing changed in between"
ONLY_UNRELATED_CHANGED = (
    "the same command passed later; only changes to files it never names came between, "
    "so what made it pass is not known"
)
_SCRIPT_RUNNERS = ("run", "run-script")  # `npm run <script>`: the script is part of the subcommand
_BARE_WORD = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class Resolution:
    """The steps that resolved a pain point, in the order they ran; the last one settled it."""

    steps: tuple[Record, ...]
    # Changes made between a failure and its pass that touch no file the failure
    # names: reported as having happened, never as the fix.
    alongside: tuple[Record, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an empty resolution: no steps means no resolution, which needs a reason."""
        if not self.steps:
            raise ValueError("a resolution needs at least one step")


class Unresolved(str):
    """A reason for no resolution that keeps the unrelated changes seen meanwhile.

    A `str`, so every caller that only wants the reason is unaffected.
    """

    alongside: tuple[Record, ...]

    def __new__(cls, reason: str, alongside: tuple[Record, ...] = ()) -> "Unresolved":
        """The reason, carrying the changes reported alongside it."""
        self = super().__new__(cls, reason)
        self.alongside = alongside
        return self


NoResolution = str  # why the history holds no resolution
Finder = Callable[[PainPoint, list[Record], Sequence[Record]], Resolution | NoResolution]


def resolution_of(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """Find what resolved `pain`; `records` is its whole chain in the order it ran."""
    return _BY_SIGNAL[pain.signature.signal](pain, cited, records)


def is_action(record: Record) -> bool:
    """A command, or an edit the harness applied."""
    return record.kind == Kind.COMMAND or applied_edit(record)


def session_from(record: Record, records: Sequence[Record]) -> list[Record]:
    """`record` and everything after it in its session."""
    return [r for r in records if r.session_id == record.session_id and r.step >= record.step]


# --- per signal ----------------------------------------------------------------


def _failed_command(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """What changed before the same command passed; a stated reason when nothing did."""
    (failed,) = cited
    success = _later_success_of(failed, records)
    if success is None:
        return NO_LATER_SUCCESS
    fixes, others = _changes_between(failed, success, records)
    if not fixes and success.command == failed.command:
        return Unresolved(ONLY_UNRELATED_CHANGED, others) if others else NOTHING_CHANGED
    return Resolution((*fixes, success), others)


def _changes_between(
    failed: Record, success: Record, records: Sequence[Record]
) -> tuple[tuple[Record, ...], tuple[Record, ...]]:
    """(changes that bear on the failure, other changes), between the failure and the pass."""
    between = [
        r
        for r in session_from(failed, records)
        if failed.step < r.step < success.step and changes_workspace(r)
    ]
    fixes = tuple(r for r in between if _bears_on(r, failed))
    return fixes, tuple(r for r in between if not _bears_on(r, failed))


def _later_success_of(failed: Record, records: Sequence[Record]) -> Record | None:
    """The first later pass of the same command: same program, subcommand and target.

    The subcommand (and the script of `npm run`) is compared before normalization drops it.
    """
    wanted = (normalise_command(failed.command or ""), _subcommand(failed.command or ""))
    return next(
        (
            later
            for later in session_from(failed, records)[1:]
            if later.kind == Kind.COMMAND
            and later.exit_code == 0
            and (normalise_command(later.command or ""), _subcommand(later.command or "")) == wanted
        ),
        None,
    )


def _subcommand(command: str) -> str:
    """The first argument when it is a bare word (`push` in `git push origin`), else "-".

    Paths and node ids are left to `normalise_command`, which already compares the target.
    """
    _, args = program_words(command)
    words = [arg for arg in args if not arg.startswith("-")] or ["-"]
    if not _BARE_WORD.match(words[0]):
        return "-"
    if words[0] in _SCRIPT_RUNNERS and len(words) > 1:
        return f"{words[0]} {words[1]}"
    return words[0]


def _bears_on(change: Record, failed: Record) -> bool:
    """An install or config change always may; an edit only to a file the failure names."""
    if not change.files:
        return True
    named = f"{failed.command or ''}\n{failed.raw}"
    return any(_names(named, path) for path in change.files)


def _names(text: str, path: str) -> bool:
    """True when the text names the path or its base name."""
    if path in text:
        return True
    base = path.rsplit("/", 1)[-1]
    return re.search(rf"(?<![\w.-]){re.escape(base)}\b", text) is not None


def _correction(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """The action that followed a user correction."""
    (turn,) = cited
    action = next((r for r in session_from(turn, records)[1:] if is_action(r)), None)
    if action is None:
        return "no edit or command followed the correction"
    return Resolution((action,))


def _reworked_edit(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """The last version of the reworked file."""
    return Resolution((_last_version(cited[-1], pain.signature.key[0], records),))


def _last_version(rework: Record, path: str, records: Sequence[Record]) -> Record:
    """Follow the edit forward to the version nobody redid.

    A later edit on `path` that takes out lines the current one put in replaces it.
    """
    current = rework
    for later in records[_index_of(rework, records) + 1 :]:
        if (
            applied_edit(later)
            and path in later.files
            and removed_lines(later.diff or "") & added_lines(current.diff or "")
        ):
            current = later
    return current


def _index_of(record: Record, records: Sequence[Record]) -> int:
    """Position of a record among all records."""
    return next(
        position
        for position, candidate in enumerate(records)
        if (candidate.session_id, candidate.step) == (record.session_id, record.step)
    )


def _review_flag(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """The answer that followed a review flag."""
    _, answer = cited
    return Resolution((answer,))


def _blast_radius(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """The edit that fixed the broken dependent, if the history shows one."""
    path, dependent = pain.signature.key
    _, failure = cited
    fix = next(
        (
            r
            for r in session_from(failure, records)[1:]
            if applied_edit(r) and ({path, dependent} & set(r.files))
        ),
        None,
    )
    if fix is None:
        return f"no later edit to {dependent} or {path} followed the failure"
    return Resolution((fix,))


def _loop(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    """A loop has no source of correction: always a stated reason."""
    return "a loop has no correction source: nothing in the history says what to do instead"


_BY_SIGNAL: dict[Signal, Finder] = {
    Signal.FAILED_COMMAND: _failed_command,
    Signal.CORRECTION: _correction,
    Signal.REWORKED_EDIT: _reworked_edit,
    Signal.REVIEW_FLAG: _review_flag,
    Signal.BLAST_RADIUS: _blast_radius,
    Signal.LOOP: _loop,
}
