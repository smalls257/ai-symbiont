"""TRAIL and Who&When traces in one minimal step form, and their per-step first-wrong-step labels.

Each reader turns its own format (span trees, chat histories) into `AnnotatedTrace`: our
`Record`s, one per agent step, plus the steps the annotators blamed; everything after the readers
reads only this form. The labels repeat our trouble label's shape (`WINDOW` steps ahead, from
`symbiont.eval.offline`) so "first wrong step ahead" scores exactly like "trouble ahead". Pure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from symbiont.core.note_rules import step_trouble
from symbiont.eval.offline import WINDOW, pain_labels
from symbiont.records.schema import Record


class TaskKind(StrEnum):
    """What the traced agent was asked to do; coding traces are the warner's own domain."""

    CODING = "coding"
    WEB_QA = "web_qa"


@dataclass(frozen=True)
class AnnotatedTrace:
    """One failed trace: records numbered from 0, and the annotated wrong steps among them.

    `first_wrong` is None when no annotation lands on a step (`unplaced_errors` says how many
    did not); such a trace is counted, never given an invented step.
    """

    source: str
    split: str
    framework: str
    task_kind: TaskKind
    records: tuple[Record, ...]
    error_steps: tuple[int, ...]
    unplaced_errors: int

    @property
    def first_wrong(self) -> int | None:
        """The earliest annotated wrong step, or None when none was placed."""
        return min(self.error_steps) if self.error_steps else None


@dataclass(frozen=True)
class StepLabels:
    """Per-step labels of one trace, aligned with `trace.records`.

    at_first_wrong: the annotated first wrong step itself. first_wrong_ahead: it lies in the next
    `window` steps (our trouble label's shape). error_ahead: any annotated wrong step does.
    mined_trouble_*: our miner's own pain points (the current label), here or ahead.
    """

    at_first_wrong: np.ndarray
    first_wrong_ahead: np.ndarray
    error_ahead: np.ndarray
    mined_trouble_ahead: np.ndarray
    mined_trouble_here: np.ndarray
    boundary: np.ndarray


def step_labels(trace: AnnotatedTrace, window: int = WINDOW) -> StepLabels:
    """Labels of every step (see StepLabels); raises ValueError unless steps run 0, 1, 2, ..."""
    steps = [record.step for record in trace.records]
    if steps != list(range(len(steps))):
        raise ValueError(f"{trace.records[0].session_id}: steps are not numbered 0..n-1")
    mined = {point.step for point in pain_labels(trace.records, {}, frozenset())}
    first = trace.first_wrong
    return StepLabels(
        at_first_wrong=np.asarray([s == first for s in steps]),
        first_wrong_ahead=_ahead(steps, () if first is None else (first,), window),
        error_ahead=_ahead(steps, trace.error_steps, window),
        mined_trouble_ahead=_ahead(steps, tuple(mined), window),
        mined_trouble_here=np.asarray([s in mined for s in steps]),
        boundary=np.asarray([_is_boundary(trace.records[: s + 1]) for s in steps]),
    )


def _ahead(steps: Sequence[int], marked: Sequence[int], window: int) -> np.ndarray:
    """True where a marked step lies in (step, step + window]."""
    return np.asarray([any(s < m <= s + window for m in marked) for s in steps])


def _is_boundary(prefix: Sequence[Record]) -> bool:
    """A pause the warner may speak at: the service's own rule."""
    return step_trouble(prefix) is not None
