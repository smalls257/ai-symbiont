"""The logistic warner: a fitted classifier on the 86 features fills the Decider slot.

T46 found a plain batch logistic regression the best warner on these features (option A value
0.173 per 100 steps against 0.090 for counters on sqlglot TRAIN) [measured]. It is fitted offline
by `scripts/routea/fit_warner.py`; this module only applies weights passed in as numbers. The risk
lives in the Decision's risk field; callers see the kind of trouble in domain terms.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.core.features import N_FEATURES
from symbiont.core.note_rules import step_trouble
from symbiont.core.slot import Decision, Outcome, Situation

NOT_A_PAUSE = "not a pause a hook can speak at"
LOOKS_ROUTINE = "this step looks routine"
_CLIP = 30.0  # logit clip, as at fitting time: exp() stays finite


class WarnerWeightsError(ValueError):
    """The weights do not describe a warner over the 86 features; the message names the field."""


@dataclass(frozen=True)
class WarnerWeights:
    """Standardization, coefficients (intercept first) and the note threshold of one fit."""

    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    note_at: float

    def __post_init__(self) -> None:
        """Refuse weights of the wrong shape, non-finite values or a threshold outside (0, 1)."""
        _require_shape("mean", self.mean, N_FEATURES)
        _require_shape("scale", self.scale, N_FEATURES)
        _require_shape("coef", self.coef, N_FEATURES + 1)
        if not np.all(self.scale > 0):
            raise WarnerWeightsError("scale must be positive in every column")
        if not 0.0 < self.note_at < 1.0:
            raise WarnerWeightsError(f"note_at must lie in (0, 1), got {self.note_at}")


def _require_shape(name: str, values: np.ndarray, size: int) -> None:
    """Raise WarnerWeightsError unless `values` holds `size` finite numbers."""
    if values.shape != (size,):
        raise WarnerWeightsError(f"{name} must hold {size} numbers, got shape {values.shape}")
    if not np.all(np.isfinite(values)):
        raise WarnerWeightsError(f"{name} holds a value that is not finite")


def weights_from(document: Mapping[str, Any]) -> WarnerWeights:
    """Weights from the decoded weights file; raises WarnerWeightsError naming what is missing."""
    try:
        mean, scale, coef = (_numbers(document[name]) for name in ("mean", "scale", "coef"))
        note_at = float(document["note_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WarnerWeightsError(f"weights file is missing or misshapes a field: {exc}") from exc
    return WarnerWeights(mean, scale, coef, note_at)


def _numbers(values: Sequence[float]) -> np.ndarray:
    """The values as a float64 array."""
    return np.asarray([float(v) for v in values], dtype=np.float64)


def warner_risk(weights: WarnerWeights, x: np.ndarray) -> float:
    """Probability that trouble follows within five steps, under the class-weighted fit."""
    standard = (np.asarray(x, dtype=np.float64) - weights.mean) / weights.scale
    logit = float(weights.coef[0] + standard @ weights.coef[1:])
    return float(1.0 / (1.0 + np.exp(-np.clip(logit, -_CLIP, _CLIP))))


class LogisticWarner:
    """Speaks at a boundary step whose risk reaches the fitted note threshold.

    Learning is offline (refit with the script); `learn` returns the state unchanged.
    """

    name = "logistic"

    def __init__(self, weights: WarnerWeights) -> None:
        """Hold the fitted weights."""
        self._weights = weights

    def decide(self, x: np.ndarray, situation: Situation, state: Any) -> Decision:
        """Name the current step's trouble when it is a boundary and the risk reaches note_at."""
        trouble = step_trouble(situation.session_prefix)
        risk = warner_risk(self._weights, x)
        if trouble is None:
            return Decision(None, (), (), reason_none=NOT_A_PAUSE, risk=risk)
        if risk < self._weights.note_at:
            return Decision(None, (), (), reason_none=LOOKS_ROUTINE, risk=risk)
        return Decision(trouble, (), (), reason_none=None, risk=risk)

    def learn(self, x: np.ndarray, outcome: Outcome, state: Any) -> Any:
        """The weights are fitted offline, so live outcomes change nothing."""
        return state

    def initial_state(self, seed: int) -> Any:
        """No state: the weights are the whole learner."""
        return None
