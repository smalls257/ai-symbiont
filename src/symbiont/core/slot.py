"""The Decider slot: the one interface every learner fills.

Counters, similarity search and the mushroom body all implement `Decider`.
Callers hand in a `Situation` and get back a `Decision`; nothing outside the
slot knows which learner is loaded. State is passed in and returned, never
held, so a learner can be swapped, replayed or run with no clock or storage.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from symbiont.miner.painpoint import PainPoint, Signature
from symbiont.records.schema import Record

NO_HISTORY = "no history for this project yet"
# A false alarm costs as much as a miss: the balanced case, and the value that
# leaves a learner's behavior as it was before warnings were penalized.
BALANCED_FALSE_ALARM_COST = 1.0


@dataclass(frozen=True)
class Situation:
    """Where the agent is.

    The session so far (the last record is the current step), pain points
    mined from earlier work, and past records worth recalling.
    """

    project: str
    session_prefix: tuple[Record, ...]
    history: tuple[PainPoint, ...]
    candidates: tuple[Record, ...]


@dataclass(frozen=True)
class Decision:
    """What the learner thinks of this step.

    Staying quiet must say why, so a silent learner can be told apart from a
    broken one.
    """

    trouble: Signature | None
    why: tuple[PainPoint, ...]
    recall: tuple[Record, ...]
    reason_none: str | None
    # For the warning-budget analysis only (higher = more likely trouble; None
    # when a learner has no such score). Hidden from repr so no f-string of a
    # Decision can carry it into a note: notes are prose, never scores.
    risk: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Refuse a silent decision that gives no reason."""
        if self.trouble is None and not self.recall and not self.reason_none:
            raise ValueError("a decision with no trouble and no recall needs a reason_none")


def event_fields(decision: Decision) -> dict[str, object]:
    """The sanctioned dict of a Decision for logs and events.

    Names what happened (the kind of trouble, how much evidence, why quiet)
    and never the risk: `dataclasses.asdict` walks every field and would carry
    it, so no log or export builds a dict from a Decision any other way.
    """
    trouble = decision.trouble
    return {
        "trouble": None if trouble is None else [trouble.signal.value, *trouble.key],
        "evidence": len(decision.why),
        "recalled": len(decision.recall),
        "reason_none": decision.reason_none,
    }


@dataclass(frozen=True)
class Outcome:
    """What happened after the step: did the predicted kind of trouble follow?"""

    pain_point_followed: bool
    signature: Signature | None
    # Where the trouble happened, so a learner that also sees it in mined
    # history counts it once. None when the caller cannot say.
    session_id: str | None = None
    step: int | None = None
    # What a false alarm costs relative to a miss (owner, Oct 27: warnings are
    # penalized). Only read when `pain_point_followed` is False.
    false_alarm_cost: float = BALANCED_FALSE_ALARM_COST

    def __post_init__(self) -> None:
        """Refuse a cost that is not a positive finite number."""
        if not 0 < self.false_alarm_cost < float("inf"):
            raise ValueError(f"false_alarm_cost must be positive, got {self.false_alarm_cost}")


class Decider(Protocol):
    """The one interface every learner fills."""

    name: str

    def decide(self, x: np.ndarray, situation: Situation, state: Any) -> Decision:
        """Judge this step; `state` is read, never changed."""
        ...

    def learn(self, x: np.ndarray, outcome: Outcome, state: Any) -> Any:
        """Returns the new state; the old one is left untouched."""
        ...

    def initial_state(self, seed: int) -> Any:
        """The state a fresh run starts from, deterministic given `seed`."""
        ...
