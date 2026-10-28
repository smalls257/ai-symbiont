"""When a warner may speak: T46 option A, the delivery rule the scored run priced.

Violation this shape prevents: Paper Tiger. A classifier that is right about a trouble spell but
speaks on five steps in a row reads as noise, and an untimed note mid-flow is ignored. So a note
goes out only at a pause a hook can see (a boundary step), at most twice a session, and never in
the five steps after the last one (docs/design/2026-10-28-note-cost.md, option A).

Pure: the session prefix and the positions already spoken come in as arguments.
"""

from collections.abc import Sequence

from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.records.schema import Kind, Record

# Option A: at most 2 notes per session, and none in the 5 steps after a note (the label
# window), so a live harness approximates "one note per trouble spell".
NOTE_BUDGET = 2
NOTE_COOLDOWN = 5


def step_trouble(prefix: Sequence[Record]) -> Signature | None:
    """The kind of trouble the current step is, when it is a boundary; None otherwise.

    A boundary is a failed command (the miner's rule, so an empty grep is not a failure) or an
    edit of a file this session already edited and applied.
    """
    if not prefix:
        return None
    current = prefix[-1]
    failed = find_failed_commands([current])
    if failed:
        return failed[0].signature
    if current.kind == Kind.EDIT and current.files:
        reedited = [path for path in current.files if path in _applied_edits(prefix[:-1])]
        if reedited:
            return Signature(Signal.REWORKED_EDIT, (reedited[0],))
    return None


def _applied_edits(earlier: Sequence[Record]) -> set[str]:
    return {
        path
        for record in earlier
        if record.kind == Kind.EDIT and record.exit_code != 1
        for path in record.files
    }


def may_speak(spoken: Sequence[int], position: int) -> bool:
    """Whether a note may go out at `position`, given the positions this session already spoke at.

    Positions are step indices within one session, in the order they happened.
    """
    if len(spoken) >= NOTE_BUDGET:
        return False
    return not spoken or position - spoken[-1] > NOTE_COOLDOWN
