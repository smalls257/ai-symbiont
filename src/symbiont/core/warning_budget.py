"""Warning budget: how often a learner may speak, and what a wrong warning teaches.

Violation prevented: **Paper Tiger**. The G6 selection judged learners on
balanced accuracy, which let each learner's own operating point decide how
many warnings to spend (the fly warned on most steps). A learner that is
"accurate" while the user drowns in false warnings meets the spec and fails
the need. So the operating point is a budget: a share of steps allowed to
warn, fixed on TRAIN (`calibrate_budget`) and enforced live (`WarningBudget`).

Second guard, **Silent Fallback**: a warning nobody checked again teaches the
learner nothing. `WarningBudget.settle` turns every admitted warning into an
`Outcome` (followed, or a false alarm after 5 steps) for the learner to learn
from. The policy is a function of (state, step), passed in and returned: no
clock, no hidden mutation (**Infected Core**).

The learn rule's direction, which the tests pin: a false alarm is a calm
outcome for the pattern that warned, so the fly relaxes that pattern's output
weights and its risk falls. It relaxes at a tenth of the strength of a
punishment (`mushroom._RELAX`), so one false alarm only partly undoes one
miss. Counters have no such decay: a false alarm leaves their tally alone.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from symbiont.core.slot import Outcome
from symbiont.miner.painpoint import Signature

# The label window of the offline replay (a pain point at steps t+1..t+5): a
# warning is a false alarm when its signature has not followed by then.
FOLLOW_WINDOW = 5
# The 0.15 budget over 20 steps is 3 warnings; this is the live default.
DEFAULT_BUDGET = 0.15
DEFAULT_PER_STEPS = 20
# What a false alarm costs relative to a miss. 1.0 is balanced; a placeholder
# like the fly's trouble threshold: the next selection's prereg fixes the real
# value (owner, Oct 27: warnings are penalized).
DEFAULT_FALSE_ALARM_COST = 1.0
_SHARE_ROUNDING = 9  # shares closer than this are ties, so float fuzz cannot decide


def warn_probability_threshold(false_alarm_cost: float) -> float:
    """The trouble probability above which warning beats staying quiet.

    Warning when trouble follows saves a miss (cost 1); warning when it does
    not costs `false_alarm_cost`. Warn when p * 1 > (1 - p) * cost.
    """
    if not 0 < false_alarm_cost < float("inf"):
        raise ValueError(f"a false alarm cost must be positive, got {false_alarm_cost}")
    return false_alarm_cost / (1.0 + false_alarm_cost)


def calibrate_budget(risks_on_train: Sequence[float | None], budget: float) -> float:
    """The risk threshold that flags `budget` of the TRAIN steps.

    A step is flagged when its risk is at or above the threshold. Risks come
    in a few discrete values for counters, so the exact share may be
    unreachable: the closest achievable share wins, ties going to the higher
    threshold (fewer warnings). Raises on a budget outside (0, 1), no steps,
    or a missing risk, so a learner without a risk score cannot be given an
    operating point.
    """
    if not 0 < budget < 1:
        raise ValueError(f"a warning budget is a share strictly between 0 and 1, got {budget}")
    risks = _require_risks(risks_on_train)
    if not len(risks):
        raise ValueError("cannot calibrate a budget on zero train steps")
    ordered = np.sort(risks)
    candidates = np.unique(ordered)
    shares = (len(ordered) - np.searchsorted(ordered, candidates, side="left")) / len(ordered)
    gaps = np.round(np.abs(shares - budget), _SHARE_ROUNDING)
    # Candidates ascend, so the last tie is the highest threshold.
    best = np.flatnonzero(gaps == gaps.min())[-1]
    return float(candidates[best])


def flagged_at(risks: Sequence[float | None], threshold: float) -> list[bool]:
    """Which steps warn at this threshold; a missing risk raises, not counts as quiet."""
    return [bool(r >= threshold) for r in _require_risks(risks)]


def _require_risks(risks: Sequence[float | None]) -> np.ndarray:
    if any(r is None for r in risks):
        raise ValueError("a step has no risk score; only learners that report one get a budget")
    return np.asarray(risks, dtype=np.float64)


class Admission(StrEnum):
    """What the budget decided about one warning."""

    ALLOWED = "allowed"
    REPEAT = "repeat of a recent warning"
    CAPPED = "over the session cap"


@dataclass(frozen=True)
class Warned:
    """An admitted warning waiting to learn whether trouble followed.

    `x` is the learner's input at that step, kept so the lesson lands on the
    pattern that warned (not compared: arrays have no useful equality).
    """

    step: int
    signature: Signature
    x: np.ndarray = field(compare=False)


@dataclass(frozen=True)
class Settled:
    """A warning's verdict, ready for `learner.learn(x, outcome, state)`."""

    x: np.ndarray = field(compare=False)
    outcome: Outcome


@dataclass(frozen=True)
class BudgetState:
    """Recent admitted warnings (cap and repeat checks) and the unsettled ones.

    Never mutated; each call returns a new one.
    """

    admitted: tuple[tuple[int, Signature], ...] = ()
    unsettled: tuple[Warned, ...] = ()


@dataclass(frozen=True)
class WarningBudget:
    """The live cap on warnings and on repeats of one signature.

    At most `max_warnings` in any `per_steps` steps, and no repeat of the same
    signature within `repeat_window` steps. Defaults come from the 0.15 budget
    of the exploratory analysis (3 in 20).
    """

    max_warnings: int = round(DEFAULT_BUDGET * DEFAULT_PER_STEPS)
    per_steps: int = DEFAULT_PER_STEPS
    repeat_window: int = FOLLOW_WINDOW
    false_alarm_cost: float = DEFAULT_FALSE_ALARM_COST

    @classmethod
    def for_budget(
        cls, share: float, *, per_steps: int, false_alarm_cost: float = DEFAULT_FALSE_ALARM_COST
    ) -> "WarningBudget":
        """The cap that spends `share` of `per_steps` steps, at least one warning."""
        return cls(
            max_warnings=max(1, round(share * per_steps)),
            per_steps=per_steps,
            false_alarm_cost=false_alarm_cost,
        )

    def admit(
        self, state: BudgetState, step: int, signature: Signature, x: np.ndarray
    ) -> tuple[Admission, BudgetState]:
        """Decide whether this warning may be spoken.

        A suppressed repeat does not use up the cap; only a spoken warning is
        remembered.
        """
        recent = tuple((s, sig) for s, sig in state.admitted if step - s < self.per_steps)
        kept = BudgetState(recent, state.unsettled)
        if any(sig == signature and step - s < self.repeat_window for s, sig in recent):
            return Admission.REPEAT, kept
        if len(recent) >= self.max_warnings:
            return Admission.CAPPED, kept
        admitted = BudgetState(
            recent + ((step, signature),), state.unsettled + (Warned(step, signature, x),)
        )
        return Admission.ALLOWED, admitted

    def settle(
        self, state: BudgetState, step: int, seen: frozenset[Signature]
    ) -> tuple[BudgetState, tuple[Settled, ...]]:
        """Close warnings at `step`, given the kinds of trouble seen at this step.

        Trouble within the next FOLLOW_WINDOW steps (not on the warning step
        itself) means followed; otherwise the warning is a false alarm once
        the window has run out.
        """
        settled, still_open = [], []
        for warned in state.unsettled:
            lesson = _lesson(warned, step, seen, self.false_alarm_cost)
            if lesson is None:
                still_open.append(warned)
            else:
                settled.append(lesson)
        return BudgetState(state.admitted, tuple(still_open)), tuple(settled)


def _lesson(warned: Warned, step: int, seen: frozenset[Signature], cost: float) -> Settled | None:
    elapsed = step - warned.step
    if elapsed <= 0:
        return None
    # `seen` is the trouble at this step only, so it counts only inside the
    # window; settle need not be called on every step.
    if elapsed <= FOLLOW_WINDOW and warned.signature in seen:
        return Settled(warned.x, Outcome(pain_point_followed=True, signature=warned.signature))
    if elapsed >= FOLLOW_WINDOW:
        false_alarm = Outcome(
            pain_point_followed=False, signature=warned.signature, false_alarm_cost=cost
        )
        return Settled(warned.x, false_alarm)
    return None
