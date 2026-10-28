"""DenseNet variants for the T47 ablation: a fixed random tanh layer, one change at a time.

Each option isolates one cause of trailing a batch classifier: `gain` and `hidden_scale` (D1,
saturation), `rate` and `rate_halflife` (D2, step size), `trouble_weight` (D3, class weighting),
`hidden` and `readout_input` (D4, capacity). The hidden layer is drawn as DenseNet draws it; the
readout is a logistic unit learned by the delta rule. A risk scorer, not a live filler: no recall.
Per session: `encode` once, `risks` with the state frozen, then `learn` the steps in order.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from symbiont.core.dense import N_HIDDEN
from symbiont.core.features import N_FEATURES
from symbiont.core.input_gain import InputGain


class ReadoutInput(StrEnum):
    """What the readout sees."""

    HIDDEN = "hidden"  # DenseNet's readout
    HIDDEN_AND_INPUTS = "hidden_and_inputs"  # plus a skip from the (gained) inputs


@dataclass(frozen=True)
class DenseVariantState:
    """Fixed hidden layer and the learned readout; `learn` returns a new one."""

    hidden_w: np.ndarray  # (hidden, N_FEATURES), fixed from the seed
    readout: np.ndarray  # (encoded width,), starts at 0
    bias: float = 0.0
    updates: int = 0


@dataclass(frozen=True)
class DenseVariant:
    """A fixed random tanh layer with a chosen gain, step, class weight and readout."""

    seed: int
    hidden: int = N_HIDDEN
    rate: float = 0.1  # the T46 curve's DenseNet rate
    rate_halflife: float | None = None
    trouble_weight: float = 1.0
    readout_input: ReadoutInput = ReadoutInput.HIDDEN
    gain: InputGain | None = None
    hidden_scale: float = 1.0

    def __post_init__(self) -> None:
        """Refuse a layer with no units or a class weight that is not positive."""
        if self.hidden < 1:
            raise ValueError(f"a dense variant needs at least one hidden unit, got {self.hidden}")
        if not self.trouble_weight > 0:
            raise ValueError(f"trouble weight must be positive, got {self.trouble_weight}")

    def initial_state(self, seed: int) -> DenseVariantState:
        """Hidden weights drawn as DenseNet draws them; readout and bias 0."""
        rng = np.random.default_rng([self.seed, seed])
        hidden_w = self.hidden_scale * rng.standard_normal((self.hidden, N_FEATURES))
        skip = N_FEATURES if self.readout_input == ReadoutInput.HIDDEN_AND_INPUTS else 0
        return DenseVariantState(hidden_w=hidden_w, readout=np.zeros(self.hidden + skip))

    def gained(self, rows: np.ndarray) -> np.ndarray:
        """The inputs after the gain stage, as a (steps, inputs) matrix."""
        rows = np.atleast_2d(np.asarray(rows, dtype=np.float64))
        return rows if self.gain is None else self.gain.apply(rows)

    def encode(self, rows: np.ndarray, state: DenseVariantState) -> np.ndarray:
        """What the readout sees for each step: scaled hidden activity, then any skip."""
        inputs = self.gained(rows)
        hidden: np.ndarray = np.tanh(inputs @ state.hidden_w.T) / np.sqrt(self.hidden)
        if self.readout_input == ReadoutInput.HIDDEN:
            return hidden
        return np.hstack([hidden, inputs])

    def step_risks(self, encoded: np.ndarray, state: DenseVariantState) -> np.ndarray:
        """Probability of trouble for each encoded step under a frozen state."""
        return _sigmoid(encoded @ state.readout + state.bias)

    def rate_at(self, updates: int) -> float:
        """The readout step after `updates` learned steps."""
        if self.rate_halflife is None:
            return self.rate
        return self.rate / (1.0 + updates / self.rate_halflife)

    def learn(
        self, encoded: np.ndarray, followed: np.ndarray, state: DenseVariantState
    ) -> DenseVariantState:
        """Delta rule on the readout and bias, step by step in order."""
        readout, bias, updates = state.readout.copy(), state.bias, state.updates
        for phi, trouble in zip(encoded, followed, strict=True):
            error = float(_sigmoid(phi @ readout + bias)) - float(trouble)
            step = self.rate_at(updates) * error * (self.trouble_weight if trouble else 1.0)
            readout -= step * phi
            bias -= step
            updates += 1
        return replace(state, readout=readout, bias=bias, updates=updates)


def _sigmoid(logit: np.ndarray | float) -> np.ndarray:
    """Logistic function, clipped so extreme logits do not overflow."""
    result: np.ndarray = 1.0 / (1.0 + np.exp(-np.clip(logit, -30.0, 30.0)))
    return result
