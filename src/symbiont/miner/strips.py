"""One session drawn step by step: who spoke, what was edited, what failed or passed.

A number of "turns lost" says nothing until the developer can
see the stretch it came from. A strip keeps only names (program, target, file), never output.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.miner.attempts import failed
from symbiont.miner.changes import applied_edit
from symbiont.miner.commands import normalise_command
from symbiont.miner.failure_keys import is_interrupt
from symbiont.miner.struggle import BURST_FAILURES, BURST_STEPS
from symbiont.miner.themes import Codebase
from symbiont.records.schema import Kind, Record

LABEL_CHARS = 44
# A strip is a picture, not a transcript: a longer session is cut here, and says so on the page.
MAX_STRIP_STEPS = 600
BURST_WEIGHT = 1000  # one failure burst outweighs any difference in session length
IDEAL_STEPS = 150  # between sessions equally bursty, the one nearest this reads best on a page
READABLE_STEPS = range(40, 261)


class Lane(StrEnum):
    """Which row of the strip a step sits on, and what it was."""

    YOU = "you"
    CODE_EDIT = "edit"
    SCRATCH_EDIT = "scratch"
    FAILED = "failed"
    PASSED = "passed"


@dataclass(frozen=True)
class StripStep:
    """One step: its number in the session, its lane and a short name."""

    step: int
    lane: Lane
    label: str


@dataclass(frozen=True)
class SessionStrip:
    """A session's strip with the label of its task and how dense its worst stretch was."""

    session_id: str
    task_label: str
    burst: int
    steps: tuple[StripStep, ...]


def strip_of(session: Sequence[Record], codebase: Codebase) -> tuple[StripStep, ...]:
    """The session's user turns, edits and commands as steps (Ctrl-C and its friends left out)."""
    steps = (_step(record, codebase) for record in session)
    return tuple(step for step in steps if step is not None)[:MAX_STRIP_STEPS]


def _step(record: Record, codebase: Codebase) -> StripStep | None:
    """The step a record draws, or None when it is not drawn."""
    if record.kind == Kind.USER_TURN:
        return StripStep(record.step, Lane.YOU, "you")
    if applied_edit(record) and record.files:
        relative = codebase.relative(record.files[0])
        lane = Lane.CODE_EDIT if relative is not None else Lane.SCRATCH_EDIT
        return StripStep(record.step, lane, (relative or record.files[0])[:LABEL_CHARS])
    if record.kind == Kind.COMMAND and not is_interrupt(record):
        program, target = normalise_command(record.command or "")
        lane = Lane.FAILED if failed(record) else Lane.PASSED
        return StripStep(record.step, lane, f"{program} {target}"[:LABEL_CHARS])
    return None


def burstiness(session: Sequence[Record]) -> int:
    """How dense the worst stretch of failures is: bursts weigh more than any session length."""
    steps = [r.step for r in session if failed(r)]
    bursts = sum(_in_window(first, steps) >= BURST_FAILURES for first in steps)
    return bursts * BURST_WEIGHT - abs(len(session) - IDEAL_STEPS)


def _in_window(first: int, steps: Sequence[int]) -> int:
    """How many failing steps fall in the window that opens at `first`."""
    return sum(first <= step < first + BURST_STEPS for step in steps)
