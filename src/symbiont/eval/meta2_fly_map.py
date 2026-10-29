"""The fly's dopamine rule over one task as one affine map per synapse. Pure numpy.

Each update is affine in a synapse's weight (depress: times 1 - rate; relax: a share toward 1),
so a task composes to `after = scale * before + shift`, independent of the weights. The META2
torch unroll applies these maps to differentiate a start through the fly's exact rule.
"""

from dataclasses import dataclass

import numpy as np

from symbiont.core.fly_variants import SAFE_RATE_SHARE, FlyVariant, FlyVariantState, Valence
from symbiont.core.mushroom import N_KC, RELAX_RATIO


@dataclass(frozen=True)
class SynapseMap:
    """One output side's per-task map: (compartments, N_KC) scale and shift."""

    scale: np.ndarray
    shift: np.ndarray

    def apply(self, weights: np.ndarray) -> np.ndarray:
        """The weights after the task."""
        result: np.ndarray = self.scale * weights + self.shift
        return result


@dataclass(frozen=True)
class TaskMap:
    """Both output sides' maps for one task; `avoid` is the identity for a one-sided fly."""

    approach: SynapseMap
    avoid: SynapseMap


def _identity(compartments: int) -> tuple[np.ndarray, np.ndarray]:
    return np.ones((compartments, N_KC)), np.zeros((compartments, N_KC))


def _compose(
    side: tuple[np.ndarray, np.ndarray], cells: np.ndarray, factor: np.ndarray, add: np.ndarray
) -> None:
    """Follow the current map of `cells` by w -> factor * w + add, in place."""
    scale, shift = side
    scale[:, cells] *= factor
    shift[:, cells] = factor * shift[:, cells] + add


def task_map(fly: FlyVariant, codes: np.ndarray, followed: np.ndarray) -> TaskMap:
    """The composed map of `fly.learn` over one task's steps, in order."""
    rates = np.asarray(fly.rates)[:, None]
    relax = rates * min(1.0, RELAX_RATIO * fly.false_alarm_cost)
    safe = rates * SAFE_RATE_SHARE
    approach, avoid = _identity(len(fly.rates)), _identity(len(fly.rates))
    two = fly.valence == Valence.TWO_VALENCE
    for cells, trouble in zip(codes, followed, strict=True):
        if trouble:
            _compose(approach, cells, 1.0 - rates, np.zeros_like(rates))
        else:
            _compose(approach, cells, 1.0 - relax, relax)
        if two and trouble:
            _compose(avoid, cells, 1.0 - relax, relax)
        elif two:
            _compose(avoid, cells, 1.0 - safe, np.zeros_like(safe))
    return TaskMap(SynapseMap(*approach), SynapseMap(*avoid))


def apply_map(state: FlyVariantState, mapped: TaskMap, steps: int) -> FlyVariantState:
    """The state `fly.learn` would return for the task the map was built from."""
    return FlyVariantState(
        wiring=state.wiring,
        approach=mapped.approach.apply(state.approach),
        avoid=mapped.avoid.apply(state.avoid),
        updates=state.updates + steps,
    )
