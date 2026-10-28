"""The T47 ablation's learners: one row per mechanism, each with its R1 and R2 regimes.

Violation prevented: **Forensic Coding**. A row named "fly H2" means nothing a week later; each
arm here carries its hypothesis, the biology (or the network fix) it maps to, and how it is
refit between sessions, so the results file can be read without this code.

Every arm is built from what the training repositories alone fix: the input gain and the
trouble share. Nothing here reads a scoring repository.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.core.dense import DenseNet
from symbiont.core.dense_variants import DenseVariant, ReadoutInput
from symbiont.core.fly_variants import FlyVariant, Valence
from symbiont.core.input_gain import InputGain
from symbiont.core.slot import Outcome
from symbiont.eval.batch_refit import REFIT_PRIOR, dense_as_net, refit_readout
from symbiont.eval.regime_replay import OnlineScorer, Refit, consolidation
from symbiont.eval.tanh_net import NetScorer, fine_tune

CONSOLIDATION_PASSES = 3  # "several passes"; not tuned
SLOW_RATE = 0.01  # a tenth of the fast rate: about ten times the memory (H1 [measured])
DECAY_HALFLIFE = 20_000.0  # updates; about the steps of four pool repositories
CURVE_DENSE_RATE = 0.1  # the T46 curve's DenseNet readout rate
WIDE = 512


@dataclass(frozen=True)
class Fixed:
    """What the training repositories fix before any arm is built."""

    gain: InputGain
    trouble_share: float

    @property
    def balance(self) -> float:
        """Trouble weight that gives both classes equal total weight."""
        return (1 - self.trouble_share) / self.trouble_share


@dataclass(frozen=True)
class Arm:
    """One learner of the table and how it is built for a wiring seed."""

    name: str
    family: str  # fly, dense
    hypothesis: str
    maps_to: str
    build: Callable[[int, Fixed], OnlineScorer]
    refit: str = "consolidation"  # consolidation, readout, backprop


class DenseNetScorer:
    """The existing DenseNet (calibrator, false-alarm-weighted rule) as an online scorer."""

    def __init__(self, seed: int) -> None:
        """DenseNet at the T46 curve's rate; the replay's false-alarm cost weights its rule."""
        self._net = DenseNet(seed, lr=CURVE_DENSE_RATE)

    def initial_state(self, seed: int) -> Any:
        """DenseNet's own fresh state."""
        return self._net.initial_state(seed)

    def encode(self, rows: np.ndarray, state: Any) -> np.ndarray:
        """Raw features: DenseNet encodes inside its own rule."""
        return np.atleast_2d(rows)

    def step_risks(self, encoded: np.ndarray, state: Any) -> np.ndarray:
        """DenseNet's calibrated probability, the risk its decide reports."""
        return np.array([self._net.trouble_probability(x, state) for x in encoded])

    def learn(self, encoded: np.ndarray, followed: np.ndarray, state: Any) -> Any:
        """DenseNet's rule, step by step, at the replay's false-alarm cost of 0.5."""
        for x, trouble in zip(encoded, followed, strict=True):
            state = self._net.learn(x, Outcome(bool(trouble), None, false_alarm_cost=0.5), state)
        return state


def _fly(**options: Any) -> Callable[[int, Fixed], OnlineScorer]:
    def build(seed: int, fixed: Fixed) -> OnlineScorer:
        gain = fixed.gain if options.get("gain") else None
        rest = {k: v for k, v in options.items() if k != "gain"}
        return FlyVariant(seed, gain=gain, **rest)

    return build


def _dense(**options: Any) -> Callable[[int, Fixed], OnlineScorer]:
    def build(seed: int, fixed: Fixed) -> OnlineScorer:
        settings = dict(options)
        if settings.pop("gain", False):
            settings["gain"] = fixed.gain
        if settings.pop("balanced", False):
            settings["trouble_weight"] = fixed.balance
        return DenseVariant(seed, **settings)

    return build


FAN_IN = 1 / np.sqrt(86)
FLY_ARMS = (
    Arm("fly as is", "fly", "baseline", "existing circuit", _fly()),
    Arm(
        "fly H1 slow rate",
        "fly",
        "H1",
        "lower plasticity at the KC-MBON synapse",
        _fly(rates=(SLOW_RATE,)),
    ),
    Arm(
        "fly H1 two compartments",
        "fly",
        "H1",
        "fast and slow compartments",
        _fly(rates=(0.1, SLOW_RATE)),
    ),
    Arm("fly H2 input gain", "fly", "H2", "projection-neuron gain control", _fly(gain=True)),
    Arm(
        "fly H3 two valence",
        "fly",
        "H3",
        "approach and avoid output neurons",
        _fly(valence=Valence.TWO_VALENCE),
    ),
    Arm(
        "fly H1+H2",
        "fly",
        "combined",
        "gain control and two compartments",
        _fly(gain=True, rates=(0.1, SLOW_RATE)),
    ),
    Arm(
        "fly combined",
        "fly",
        "combined",
        "gain, two compartments, two valence",
        _fly(gain=True, rates=(0.1, SLOW_RATE), valence=Valence.TWO_VALENCE),
    ),
)
_COMBINED_DENSE = dict(
    gain=True,
    hidden_scale=FAN_IN,
    rate=1.0,
    rate_halflife=DECAY_HALFLIFE,
    balanced=True,
    readout_input=ReadoutInput.HIDDEN_AND_INPUTS,
    hidden=WIDE,
)
DENSE_ARMS = (
    Arm(
        "DenseNet as is",
        "dense",
        "baseline",
        "existing class",
        lambda seed, _: DenseNetScorer(seed),
    ),
    Arm("dense plain delta", "dense", "D0", "readout without calibrator", _dense(), "readout"),
    Arm("dense D1 gain", "dense", "D1", "input normalization", _dense(gain=True), "readout"),
    Arm(
        "dense D1 gain fan-in",
        "dense",
        "D1",
        "normalization and fan-in scale",
        _dense(gain=True, hidden_scale=FAN_IN),
        "readout",
    ),
    Arm("dense D2 rate 1", "dense", "D2", "larger step", _dense(rate=1.0), "readout"),
    Arm(
        "dense D2 decaying",
        "dense",
        "D2",
        "larger step that decays",
        _dense(rate=1.0, rate_halflife=DECAY_HALFLIFE),
        "readout",
    ),
    Arm(
        "dense D3 balanced",
        "dense",
        "D3",
        "trouble weighted by class balance",
        _dense(balanced=True),
        "readout",
    ),
    Arm(
        "dense D4 skip",
        "dense",
        "D4",
        "readout over hidden and inputs",
        _dense(readout_input=ReadoutInput.HIDDEN_AND_INPUTS),
        "readout",
    ),
    Arm("dense D4 wide", "dense", "D4", "512 hidden units", _dense(hidden=WIDE), "readout"),
    Arm(
        "dense combined",
        "dense",
        "combined",
        "D1 to D4 together",
        _dense(**_COMBINED_DENSE),
        "readout",
    ),
    Arm(
        "dense combined backprop",
        "dense",
        "combined",
        "R2 also refits the hidden layer",
        _dense(**_COMBINED_DENSE),
        "backprop",
    ),
)
ARMS = {arm.name: arm for arm in FLY_ARMS + DENSE_ARMS}


def refit_for(arm: Arm, scorer: OnlineScorer, shipped: Any) -> tuple[Any, Refit]:
    """The scorer R2 reads with, and its refit (sessions so far -> state)."""
    if arm.refit == "consolidation":
        return scorer, consolidation(scorer, shipped, CONSOLIDATION_PASSES)
    if not isinstance(scorer, DenseVariant):
        raise ValueError(f"{arm.name}: a {arm.refit} refit needs a dense variant")
    if arm.refit == "readout":
        return scorer, lambda enc, fol: refit_readout(
            scorer, shipped, np.vstack(enc), np.concatenate(fol)
        )
    net = dense_as_net(scorer, shipped)
    return _NetOfDense(scorer), _backprop(net, scorer.trouble_weight)


class _NetOfDense(NetScorer):
    """R2 backprop reads the network from raw rows: encodes with the network's own gain."""

    def __init__(self, variant: DenseVariant) -> None:
        self._variant = variant

    def encode(self, rows: np.ndarray, state: Any) -> np.ndarray:
        """Raw rows; the network's gain is applied in `risks`."""
        return np.atleast_2d(rows)

    def step_risks(self, encoded: np.ndarray, state: Any) -> np.ndarray:
        """Risk of the network, or of the shipped dense state before the first refit."""
        if not hasattr(state, "w_in"):
            return self._variant.step_risks(self._variant.encode(encoded, state), state)
        return super().step_risks(super().encode(encoded, state), state)


def _backprop(net: Any, trouble_weight: float) -> Refit:
    def refit(encoded: Sequence[np.ndarray], followed: Sequence[np.ndarray]) -> Any:
        labels = np.concatenate(followed)
        weights = np.where(labels, trouble_weight, 1.0)
        return fine_tune(net, np.vstack(encoded), labels, weights, REFIT_PRIOR)

    return refit


def timed(refit: Refit, times: list[float]) -> Refit:
    """The same refit, its wall time per call appended to `times`."""

    def run(encoded: Sequence[np.ndarray], followed: Sequence[np.ndarray]) -> Any:
        started = time.perf_counter()
        state = refit(encoded, followed)
        times.append(time.perf_counter() - started)
        return state

    return run
