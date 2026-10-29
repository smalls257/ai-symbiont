"""Fly variants for the T47 ablation: the mushroom body with one mechanism changed at a time.

Each option maps to one piece of the circuit and one hypothesis: `rates` (a rate per compartment,
H1 forgetting [established]), `gain` (projection-neuron gain, H2) and `valence` (avoid beside
approach output neurons, H3 [established]). Wiring is the existing fly's, so the default variant
is the existing fly step for step. A risk scorer, not a live filler: no recall. Per session:
`encode`, `risks` with the state frozen, then `learn` in order.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from symbiont.core.input_gain import InputGain
from symbiont.core.mushroom import N_ACTIVE, N_KC, RELAX_RATIO, Mushroom, MushroomState

# Calm steps are about five times as common as trouble steps (pool trouble share 0.18,
# T47 [measured]), so the reward side learns at a fifth of the punishment rate: both valences
# then get about the same total plasticity.
SAFE_RATE_SHARE = 0.2
BALANCED_RELAX_COST = 0.5  # the T36/T46 replay's false-alarm cost, which sets the relax rate


class Valence(StrEnum):
    """Which output neurons read the Kenyon cells."""

    ONE_SIDED = "one_sided"  # approach only: the existing fly
    TWO_VALENCE = "two_valence"  # approach and avoid


@dataclass(frozen=True)
class FlyVariantState:
    """Fixed wiring and the output weights of every compartment; `learn` returns a new one."""

    wiring: MushroomState  # inputs and tie-break jitter of the existing fly; its w_out unused
    approach: np.ndarray  # (compartments, N_KC), start at 1
    avoid: np.ndarray  # (compartments, N_KC), start at 1; unused when one-sided
    updates: int = 0


@dataclass(frozen=True)
class FlyVariant:
    """The fly with chosen compartment rates, input gain and output valence."""

    seed: int
    rates: tuple[float, ...] = (0.1,)
    valence: Valence = Valence.ONE_SIDED
    gain: InputGain | None = None
    false_alarm_cost: float = BALANCED_RELAX_COST

    def __post_init__(self) -> None:
        """Refuse a fly with no output compartment: it could never learn."""
        if not self.rates:
            raise ValueError("a fly variant needs at least one output compartment rate")

    def initial_state(self, seed: int) -> FlyVariantState:
        """The existing fly's wiring for (self.seed, seed); every weight 1."""
        wiring = Mushroom(self.seed).initial_state(seed)
        ones = np.ones((len(self.rates), N_KC))
        return FlyVariantState(wiring=wiring, approach=ones, avoid=ones.copy())

    def encode(self, rows: np.ndarray, state: FlyVariantState) -> np.ndarray:
        """(steps, N_ACTIVE) indices of the cells each step fires: the top 5% by drive."""
        rows = np.atleast_2d(np.asarray(rows, dtype=np.float64))
        if self.gain is not None:
            rows = self.gain.apply(rows)
        drive = rows[:, state.wiring.inputs].sum(axis=2) + state.wiring.jitter
        top: np.ndarray = np.argpartition(-drive, N_ACTIVE - 1, axis=1)[:, :N_ACTIVE]
        return top

    def step_risks(self, codes: np.ndarray, state: FlyVariantState) -> np.ndarray:
        """Risk of each encoded step under a frozen state."""
        approach = state.approach[:, codes].mean(axis=2).mean(axis=0)
        if self.valence == Valence.ONE_SIDED:
            risk: np.ndarray = 1.0 - approach
            return risk
        avoid: np.ndarray = state.avoid[:, codes].mean(axis=2).mean(axis=0)
        return avoid - approach

    def learn(
        self, codes: np.ndarray, followed: np.ndarray, state: FlyVariantState
    ) -> FlyVariantState:
        """Each step's outcome in order, on copies of the weights."""
        approach, avoid = state.approach.copy(), state.avoid.copy()
        rates = np.asarray(self.rates)[:, None]
        relax = rates * min(1.0, RELAX_RATIO * self.false_alarm_cost)
        safe = rates * SAFE_RATE_SHARE
        two = self.valence == Valence.TWO_VALENCE
        for cells, trouble in zip(codes, followed, strict=True):
            _dopamine(approach, cells, punish=rates, relax=relax, trouble=bool(trouble))
            if two:
                _dopamine(avoid, cells, punish=safe, relax=relax, trouble=not trouble)
        return replace(state, approach=approach, avoid=avoid, updates=state.updates + len(codes))


def _dopamine(
    weights: np.ndarray, cells: np.ndarray, *, punish: np.ndarray, relax: np.ndarray, trouble: bool
) -> None:
    """Depress the active cells' synapses when this side's dopamine fires, else relax them."""
    if trouble:
        weights[:, cells] *= 1.0 - punish
    else:
        weights[:, cells] += relax * (1.0 - weights[:, cells])
