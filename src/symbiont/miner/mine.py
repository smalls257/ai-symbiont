"""Every pain-point signal, in one call.

Callers use this rather than each signal, so a new signal is one line here. A chain is a
developer's sessions on one repo in the order they ran; most signals look inside one session,
reworked edits also look across the chain. Parallel attempts at the same task are not a chain:
pass each alone.
"""

from collections.abc import Iterable, Mapping, Sequence

from symbiont.miner.painpoint import PainPoint
from symbiont.miner.signals.blast_radius import find_blast_radius
from symbiont.miner.signals.correction import find_corrections
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.miner.signals.loop import find_loops
from symbiont.miner.signals.review_flag import find_review_flags
from symbiont.miner.signals.reworked_edit import find_reworked_edits
from symbiont.records.schema import Record

References = Mapping[str, frozenset[str]]


def mine_chain(sessions: Sequence[Sequence[Record]], references: References) -> list[PainPoint]:
    """Mine `sessions`, given in the order they ran.

    `references[path]` = files that import or name `path` (see blast_radius); `{}`
    when there is no repo checkout, and blast radius then finds nothing.
    """
    found = [p for session in sessions for p in _within_session(session, references)]
    found += find_reworked_edits([record for session in sessions for record in session])
    return found


def mine_session(session: Sequence[Record], references: References) -> list[PainPoint]:
    """Mine one session as a chain of one (parallel attempts are not a chain)."""
    return mine_chain([session], references)


def _within_session(session: Sequence[Record], references: References) -> list[PainPoint]:
    """Every signal that looks inside one session."""
    return [
        *find_failed_commands(session),
        *find_loops(session),
        *find_blast_radius(session, references),
        *find_corrections(session),
        *find_review_flags(session),
    ]


def sessions_of(records: Iterable[Record]) -> list[list[Record]]:
    """Group records into sessions (one per harness and session id), each in step order."""
    grouped: dict[tuple[str, str], list[Record]] = {}
    for record in records:
        grouped.setdefault((record.harness, record.session_id), []).append(record)
    return [sorted(steps, key=lambda record: record.step) for _, steps in sorted(grouped.items())]


def mine_history(sessions: Sequence[Sequence[Record]], references: References) -> list[PainPoint]:
    """Mine a project's history: timed sessions form one chain, untimed ones are mined alone."""
    timed = sorted(
        ((start, s) for s in sessions if (start := _started(s)) is not None),
        key=lambda pair: pair[0],
    )
    found = mine_chain([s for _, s in timed], references)
    untimed = [s for s in sessions if _started(s) is None]
    return found + [p for session in untimed for p in mine_session(session, references)]


def _started(session: Sequence[Record]) -> str | None:
    """Earliest timestamp in a session, or None."""
    return min((record.ts for record in session if record.ts is not None), default=None)
