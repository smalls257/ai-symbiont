"""Meta-learnable fillers: the start of a filler, and one local step from it.

A filler states in its type that it is meta-learnable (`MetaLearnable`); `require_meta_learnable`
refuses anything else (counters) by name. Only `MetaStart` is learned: the readout start and the
`Calibrator`; wiring and rates stay fixed by the filler. `inner_step` is pure and `query_gradient`
is the analytic loss gradient, so first-order MAML or Reptile can run.
"""

from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

import numpy as np

from symbiont.core.slot import Decider, Outcome

# The default online rate for scale and bias. Never self-tuned (IDBD is on the
# spec's "do not build" list); a run may fix another value from a grid chosen on
# validation repositories (T39 controller ruling, Oct 28), passed to the filler.
CALIBRATOR_RATE = 0.5
# Wiring is a property of the filler's seed, not of a run, so a meta-learned
# start trained in one domain still fits the same filler in another.
META_RUN_SEED = 0


@dataclass(frozen=True)
class Calibrator:
    """Logistic scaling of a raw readout score into a trouble probability."""

    scale: float = 1.0
    bias: float = 0.0

    def probability(self, raw: float) -> float:
        """The probability of trouble for a raw score."""
        return float(1.0 / (1.0 + np.exp(-(self.scale * raw + self.bias))))


@dataclass(frozen=True)
class Readout:
    """A filler's view of one step: `raw = offset + readout . phi`."""

    phi: np.ndarray
    offset: float = 0.0

    def raw(self, weights: np.ndarray) -> float:
        """The raw score under these weights."""
        return float(self.offset + weights @ self.phi)


@dataclass(frozen=True)
class MetaStart:
    """Everything a filler may meta-learn: readout weights and calibrator."""

    readout: np.ndarray
    calibrator: Calibrator

    def as_vector(self) -> np.ndarray:
        """Flat copy for an outer loop: readout weights, then scale, then bias."""
        return np.concatenate([self.readout, [self.calibrator.scale, self.calibrator.bias]])

    def with_vector(self, vector: np.ndarray) -> "MetaStart":
        """The start whose flat form is `vector` (same layout as `as_vector`)."""
        if vector.shape != (len(self.readout) + 2,):
            raise ValueError(f"expected a vector of {len(self.readout) + 2}, got {vector.shape}")
        return MetaStart(vector[:-2].copy(), Calibrator(float(vector[-2]), float(vector[-1])))

    def toward(self, other: "MetaStart", step: float) -> "MetaStart":
        """Reptile move: `step` of the way from this start to `other`."""
        return self.with_vector(self.as_vector() + step * (other.as_vector() - self.as_vector()))


def weighted_dz(probability: float, outcome: Outcome) -> float:
    """D loss / d logit when a false alarm costs `outcome.false_alarm_cost` misses."""
    if outcome.pain_point_followed:
        return -(1.0 - probability)
    return outcome.false_alarm_cost * probability


def query_loss(start: MetaStart, view: Readout, outcome: Outcome) -> float:
    """The false-alarm-weighted log loss of this start on one outcome."""
    prob = start.calibrator.probability(view.raw(start.readout))
    if outcome.pain_point_followed:
        return float(-np.log(prob))
    return float(-outcome.false_alarm_cost * np.log(1.0 - prob))


def loss_gradient(start: MetaStart, view: Readout, outcome: Outcome) -> MetaStart:
    """Analytic gradient of `query_loss` with respect to the start."""
    raw = view.raw(start.readout)
    dz = weighted_dz(start.calibrator.probability(raw), outcome)
    return MetaStart(
        dz * start.calibrator.scale * view.phi,
        Calibrator(scale=dz * raw, bias=dz),
    )


def calibrator_step(
    calibrator: Calibrator, raw: float, outcome: Outcome, rate: float = CALIBRATOR_RATE
) -> Calibrator:
    """One online step of the calibrator on the weighted loss."""
    dz = weighted_dz(calibrator.probability(raw), outcome)
    return Calibrator(
        scale=calibrator.scale - rate * dz * raw,
        bias=calibrator.bias - rate * dz,
    )


@runtime_checkable
class MetaLearnable(Decider, Protocol):
    """A filler whose starting point Task 39 may meta-train."""

    def meta_start(self, state: Any) -> MetaStart:
        """The meta-learnable part of `state`."""
        ...

    def fresh_state(self, start: MetaStart) -> Any:
        """A new state whose meta-learnable part is exactly `start`."""
        ...

    def inner_step(self, start: MetaStart, x: np.ndarray, outcome: Outcome) -> MetaStart:
        """The filler's own local rule, applied once; pure."""
        ...

    def query_gradient(self, start: MetaStart, x: np.ndarray, outcome: Outcome) -> MetaStart:
        """Analytic gradient of the weighted loss on this outcome, at `start`."""
        ...

    def trouble_probability(self, x: np.ndarray, state: Any) -> float:
        """The calibrated probability that trouble follows this step."""
        ...


class NotMetaLearnableError(TypeError):
    """A filler without a meta-learnable start was given to the meta-trainer."""


def require_meta_learnable(filler: object) -> MetaLearnable:
    """The meta-trainer's door: returns `filler` typed, or raises naming it.

    Counters keep a tally of events, not weights; there is nothing to start
    from, so they fail here instead of training to no effect.
    """
    if not isinstance(filler, MetaLearnable):
        name = getattr(filler, "name", type(filler).__name__)
        raise NotMetaLearnableError(f"filler '{name}' has no meta-learnable start")
    return filler


class LinearReadoutMeta:
    """The contract for a filler whose state has `w_out` and `calibrator`.

    A filler supplies `base_state()` (its fixed wiring, fresh weights) and
    `readout_view(x, state)`; `inner_step` is then its own `learn` on a state
    rebuilt from the start, so the meta-trainer and a live run cannot drift.
    """

    def base_state(self) -> Any:
        """The state holding the fixed wiring; weights and calibrator are replaced."""
        raise NotImplementedError

    def readout_view(self, x: np.ndarray, state: Any) -> Readout:
        """The step as `raw = offset + readout . phi`."""
        raise NotImplementedError

    def learn(self, x: np.ndarray, outcome: Outcome, state: Any) -> Any:
        """The filler's local rule (Decider)."""
        raise NotImplementedError

    def meta_start(self, state: Any) -> MetaStart:
        """The readout weights and calibrator of `state`, copied."""
        return MetaStart(state.w_out.copy(), state.calibrator)

    def fresh_state(self, start: MetaStart) -> Any:
        """The filler's fixed wiring with `start` as its weights."""
        return replace(self.base_state(), w_out=start.readout.copy(), calibrator=start.calibrator)

    def inner_step(self, start: MetaStart, x: np.ndarray, outcome: Outcome) -> MetaStart:
        """One local-rule step from `start`; `start` is left untouched."""
        return self.meta_start(self.learn(x, outcome, self.fresh_state(start)))

    def query_gradient(self, start: MetaStart, x: np.ndarray, outcome: Outcome) -> MetaStart:
        """Analytic gradient of the weighted loss on this outcome, at `start`."""
        return loss_gradient(start, self.readout_view(x, self.fresh_state(start)), outcome)

    def trouble_probability(self, x: np.ndarray, state: Any) -> float:
        """Calibrated probability that trouble follows this step."""
        raw = self.readout_view(x, state).raw(state.w_out)
        return float(state.calibrator.probability(raw))
