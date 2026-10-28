"""When a note may be shown: boundary steps, a per-session budget, a cooldown and two tiers (T46).

Exploratory, TRAIN only (docs/design/2026-10-28-note-cost.md). A note is spent the way a harness
would: online, step by step, seeing only the current risk and the notes already shown this
session, so a learner right about one trouble spell does not pay five times. Pure: traces and
records in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from symbiont.eval.offline import WINDOW
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.records.schema import Kind, Record

# After a note, none for the label window: a stand-in for "one note per trouble spell" that a
# live harness can apply without knowing where the spell ends.
COOLDOWN_STEPS = WINDOW
NO_SPELL = -1


class Gate(StrEnum):
    """Which steps may carry a note at all."""

    EVERY_STEP = "every step"
    BOUNDARY = "boundary"  # right after a failed command, or at an edit of a file edited before


@dataclass(frozen=True)
class NoteTrace:
    """One replayed session: label, risk and boundary mark at every step."""

    task_id: str
    followed: tuple[bool, ...]
    step_risk: tuple[float, ...]
    boundary: tuple[bool, ...]

    def __post_init__(self) -> None:
        """Refuse a trace whose per-step columns do not line up."""
        sizes = {len(self.followed), len(self.step_risk), len(self.boundary)}
        if len(sizes) != 1:
            raise ValueError(f"task {self.task_id}: labels, risks and boundaries differ in length")


@dataclass(frozen=True)
class DeliveryRule:
    """How notes are spent in one session."""

    gate: Gate
    budget: int | None = None  # notes per session; None is no cap
    cooldown: int = 0  # steps after a note that may carry no note


def boundary_steps(session: Sequence[Record]) -> tuple[bool, ...]:
    """Steps a harness hook sees as natural pauses: a failed command, or a repeat edit of a file."""
    failed = {point.step for point in find_failed_commands(session)}
    edited: set[str] = set()
    marks = []
    for record in session:
        is_edit = record.kind == Kind.EDIT
        marks.append(record.step in failed or (is_edit and bool(edited & set(record.files))))
        if is_edit and record.exit_code != 1:
            edited.update(record.files)
    return tuple(marks)


def spell_ids(followed: Sequence[bool]) -> np.ndarray:
    """Number each maximal run of steps followed by trouble; NO_SPELL elsewhere."""
    marks = np.asarray(followed, dtype=bool)
    starts = marks & ~np.concatenate(([False], marks[:-1]))
    ids = np.cumsum(starts) - 1
    return np.where(marks, ids, NO_SPELL)


def note_steps(
    risk: np.ndarray, eligible: np.ndarray, threshold: float, rule: DeliveryRule
) -> np.ndarray:
    """Steps that carry a note, spent online: risk at threshold, within budget and cooldown."""
    candidates = np.flatnonzero(eligible & (risk >= threshold))
    if rule.budget is None and rule.cooldown == 0:
        return candidates
    shown: list[int] = []
    for step in candidates.tolist():
        if rule.budget is not None and len(shown) >= rule.budget:
            break
        if shown and step - shown[-1] <= rule.cooldown:
            continue
        shown.append(step)
    return np.asarray(shown, dtype=np.int64)
