"""Assemble the note-cost exploratory results (T46). Work in progress: the scorer lands next."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from symbiont.eval.note_delivery import NoteTrace

Traces = tuple[NoteTrace, ...]


@dataclass(frozen=True)
class Arms:
    """TRAIN traces: counters, the fly per wiring seed, DenseNet per seed and rate."""

    counters: Traces
    fly: Mapping[int, Traces]
    dense: Mapping[int, Mapping[float, Traces]]


def report(arms: Arms, *, seed: int) -> dict[str, Any]:
    """Not written yet."""
    raise NotImplementedError("the scorer is the next commit")
