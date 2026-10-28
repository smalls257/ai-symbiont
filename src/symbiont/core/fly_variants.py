"""Fly variants for the T47 ablation: the mushroom body with one mechanism changed at a time.

Violation prevented: **Paper Tiger**. The existing fly ties plain counters and trails a batch
classifier on the same features; a variant that only looked more like the fly would not say
why. Each option here maps to one piece of the fly's circuit and one hypothesis, so a row of
the ablation table can be read as "this mechanism was or was not what held the fly back":

- `rates`: one learning rate per output compartment. The mushroom body's lobes are tiled
  into compartments, each with its own dopamine neuron and output neuron, that learn and
  forget on different time scales (gamma lobe fast, alpha/beta slow; Aso et al. 2014, Aso and
  Rubin 2016) [established]. `(0.1,)` is the existing fly; a second, slower rate adds a
  long-term memory beside the short-term one (H1, forgetting).
- `gain`: projection-neuron gain control before the Kenyon cells (H2, `input_gain`).
- `valence`: avoid output neurons beside the approach ones; punishment depresses the approach
  side and reward (a calm step) the avoid side (Aso et al. 2014, output neurons of opposite
  valence) [established]. The risk is avoid minus approach, so a pattern can be learned as
  safe, not only as not-yet-punished (H3).

The wiring (86 inputs, 5,177 cells, 7 inputs per cell, top 5% fire) and the seeded tie-break
are the existing fly's, taken from `Mushroom.initial_state`, so the default variant is the
existing fly step for step (a test holds that). This is a risk scorer for the offline
ablation, not a live filler: it has no recall and names no kind of trouble. Learning is per
session: `encode` the session's steps once (the code depends only on the fixed wiring), read
`risks` with the state frozen, then `learn` the steps in order, as `offline.replay` does.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from symbiont.core.input_gain import InputGain
from symbiont.core.mushroom import _RELAX, N_ACTIVE, N_KC, Mushroom, MushroomState

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
        relax = rates * min(1.0, _RELAX * self.false_alarm_cost)
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
