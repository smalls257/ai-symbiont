"""What resolved a pain point, as the steps the history shows.

Shared by lessons (what a note says was done) and Route B (what a model is
trained to do), so the two never disagree about the fix. Finding nothing is an
answer with a stated reason, never a guess: a made-up fix is a Silent Fallback
that teaches the wrong habit.

A failed command's fix is what changed between the failure and the later run
that passed (edits, installs, configuration, a different way of running it),
not the passing run alone: re-running the same command unchanged fixes nothing.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from symbiont.miner.changes import applied_edit, changes_workspace
from symbiont.miner.commands import normalise_command
from symbiont.miner.diffs import added_lines, removed_lines
from symbiont.miner.painpoint import PainPoint, Signal
from symbiont.records.schema import Kind, Record

NO_LATER_SUCCESS = (
    "no later command with exit 0 on the same program and target followed the failure"
)
NOTHING_CHANGED = "the same command passed later with nothing changed in between"


@dataclass(frozen=True)
class Resolution:
    """The steps that resolved a pain point, in the order they ran; the last one settled it."""

    steps: tuple[Record, ...]

    def __post_init__(self) -> None:
        """Refuse an empty resolution: no steps means no resolution, which needs a reason."""
        if not self.steps:
            raise ValueError("a resolution needs at least one step")


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
    (failed,) = cited
    success = _later_success_of(failed, records)
    if success is None:
        return NO_LATER_SUCCESS
    changes = [
        r
        for r in session_from(failed, records)
        if failed.step < r.step < success.step and changes_workspace(r)
    ]
    if not changes and success.command == failed.command:
        return NOTHING_CHANGED
    return Resolution((*changes, success))


def _later_success_of(failed: Record, records: Sequence[Record]) -> Record | None:
    wanted = normalise_command(failed.command or "")
    return next(
        (
            later
            for later in session_from(failed, records)[1:]
            if later.kind == Kind.COMMAND
            and later.exit_code == 0
            and normalise_command(later.command or "") == wanted
        ),
        None,
    )


def _correction(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    (turn,) = cited
    action = next((r for r in session_from(turn, records)[1:] if is_action(r)), None)
    if action is None:
        return "no edit or command followed the correction"
    return Resolution((action,))


def _reworked_edit(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
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
    return next(
        position
        for position, candidate in enumerate(records)
        if (candidate.session_id, candidate.step) == (record.session_id, record.step)
    )


def _review_flag(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
    _, answer = cited
    return Resolution((answer,))


def _blast_radius(
    pain: PainPoint, cited: list[Record], records: Sequence[Record]
) -> Resolution | NoResolution:
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
    return "a loop has no correction source: nothing in the history says what to do instead"


_BY_SIGNAL: dict[Signal, Finder] = {
    Signal.FAILED_COMMAND: _failed_command,
    Signal.CORRECTION: _correction,
    Signal.REWORKED_EDIT: _reworked_edit,
    Signal.REVIEW_FLAG: _review_flag,
    Signal.BLAST_RADIUS: _blast_radius,
    Signal.LOOP: _loop,
}
