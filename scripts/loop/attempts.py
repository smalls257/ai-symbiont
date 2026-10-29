"""Attempts and the verify step: only graded outcomes count, and held-out work is never mined.

An ungraded attempt (Glimmer timed out, Docker died) is neither a pass nor a failure: `verified`
counts it apart and raises `UnverifiableRoundError` when too much of a round is ungraded, so no
lesson is mined from an outage. A held-out attempt offered for mining raises. Pure.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# A round with more than a quarter of its attempts ungraded is an outage, not a round
# (the 2026-10-28 hang left whole batches ungraded); its lessons would come from the outage.
MAX_UNGRADED_SHARE = 0.25


class Outcome(StrEnum):
    """The grader's verdict: hidden tests for coding, the exit for Freedoom."""

    PASSED = "passed"
    FAILED = "failed"
    UNGRADED = "ungraded"


class Split(StrEnum):
    """Which side of the declared split a task is on."""

    TRAINING = "training"
    HELD_OUT = "held_out"


class UnverifiableRoundError(RuntimeError):
    """Too many attempts of a round were never graded; nothing is mined from it."""


class HeldOutMiningError(ValueError):
    """A held-out attempt reached the harvest or the lesson-utility step."""


@dataclass(frozen=True)
class Attempt:
    """One graded (or ungraded) attempt at one task by one model in one round."""

    attempt_id: str
    task_id: str
    round_index: int
    model: str
    split: Split
    outcome: Outcome
    trained_lessons: frozenset[str] = frozenset()  # lesson ids in the model's training set

    @property
    def passed(self) -> bool:
        """Graded and passed."""
        return self.outcome is Outcome.PASSED

    def to_json(self) -> dict[str, Any]:
        """The attempt for the loop's state file: ids, labels and lesson ids, no text."""
        raw = dict(self.__dict__)
        raw["trained_lessons"] = sorted(self.trained_lessons)
        return raw

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Attempt:
        """Inverse of `to_json`."""
        return cls(
            **{
                **raw,
                "split": Split(raw["split"]),
                "outcome": Outcome(raw["outcome"]),
                "trained_lessons": frozenset(raw["trained_lessons"]),
            }
        )


@dataclass(frozen=True)
class VerifiedBatch:
    """A round's graded attempts and how many were dropped as ungraded."""

    graded: tuple[Attempt, ...]
    ungraded: int

    @property
    def passed(self) -> tuple[Attempt, ...]:
        """The verified successes: the only source of resolutions and success rows."""
        return tuple(attempt for attempt in self.graded if attempt.passed)


def verified(attempts: Sequence[Attempt]) -> VerifiedBatch:
    """Graded attempts only; raises UnverifiableRoundError above MAX_UNGRADED_SHARE ungraded."""
    graded = tuple(a for a in attempts if a.outcome is not Outcome.UNGRADED)
    ungraded = len(attempts) - len(graded)
    if attempts and ungraded / len(attempts) > MAX_UNGRADED_SHARE:
        raise UnverifiableRoundError(
            f"{ungraded} of {len(attempts)} attempts ungraded (limit {MAX_UNGRADED_SHARE:.0%}): "
            "look at the server and the grader before mining this round"
        )
    return VerifiedBatch(graded, ungraded)


def training_only(attempts: Iterable[Attempt], held_out: frozenset[str]) -> list[Attempt]:
    """The attempts, refusing any held-out one (by split label or by task id)."""
    found = list(attempts)
    leaked = sorted(
        a.attempt_id for a in found if a.split is Split.HELD_OUT or a.task_id in held_out
    )
    if leaked:
        raise HeldOutMiningError(f"held-out attempts offered for mining: {leaked}")
    return found


def pass_rate(attempts: Sequence[Attempt]) -> float | None:
    """Share of graded attempts that passed; None when none was graded."""
    graded = [a for a in attempts if a.outcome is not Outcome.UNGRADED]
    return sum(a.passed for a in graded) / len(graded) if graded else None
