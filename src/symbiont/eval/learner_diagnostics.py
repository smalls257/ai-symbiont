"""Measurements behind the T47 hypotheses: what the fly's cells code and how long they remember.

Violation prevented: **Black Box**. "The fly does not improve with more data" names no cause;
these numbers do. Each function measures one hypothesis on real steps, so a variant is tried
because a measurement showed a problem, not because it was the next idea:

- H1 forgetting: `memory_updates` and `cell_memory`. Every update of a cell is an affine map
  of its weight with slope 1 - rate (trouble) or 1 - rate * relax (calm), so an outcome's
  influence after k more updates is the product of the slopes; the e-folding length below
  is exact for that product's expected log.
- H2 input scaling and H4 code quality: `fly_code_report`.
- D1 saturation: `saturation_share`.
"""

from typing import Any

import numpy as np

from symbiont.core.dense_variants import DenseVariant, DenseVariantState
from symbiont.core.fly_variants import FlyVariant, FlyVariantState
from symbiont.core.mushroom import N_ACTIVE, N_KC

SATURATED = 0.95  # |tanh| above this passes almost no gradient and barely tells inputs apart


def memory_updates(rate: float, relax: float, trouble_share: float) -> float:
    """Updates after which an outcome's influence on a cell has fallen to 1/e."""
    log_slope = trouble_share * np.log1p(-rate) + (1 - trouble_share) * np.log1p(-rate * relax)
    return float(-1.0 / log_slope)


def cell_memory(
    codes: np.ndarray, followed: np.ndarray, rate: float, relax: float
) -> dict[str, float]:
    """Per-cell memory against how many outcomes each cell saw (cells that fired at all)."""
    updates = np.bincount(codes.ravel(), minlength=N_KC)
    trouble = np.bincount(codes[followed].ravel(), minlength=N_KC)
    fired = updates > 0
    share = trouble[fired] / updates[fired]
    memory = np.array([memory_updates(rate, relax, p) for p in share])
    return {
        "cells_that_fired_share": float(fired.mean()),
        "median_updates_per_cell": float(np.median(updates[fired])),
        "median_memory_updates": float(np.median(memory)),
        "median_share_of_outcomes_remembered": float(
            np.median(np.minimum(1.0, memory / updates[fired]))
        ),
    }


def _drive(fly: FlyVariant, state: FlyVariantState, rows: np.ndarray) -> np.ndarray:
    inputs = rows if fly.gain is None else fly.gain.apply(rows)
    drive: np.ndarray = inputs[:, state.wiring.inputs].sum(axis=2)
    return drive


def fly_code_report(
    fly: FlyVariant, state: FlyVariantState, rows: np.ndarray, watched: int
) -> dict[str, Any]:
    """How the active cells are chosen, on a sample of steps (rows; at least two)."""
    codes, drive = fly.encode(rows, state), _drive(fly, state, rows)
    active = np.take_along_axis(drive, codes, axis=1)
    weakest = active.min(axis=1, keepdims=True)
    inactive_at_weakest = (drive == weakest).sum(axis=1) - (active == weakest).sum(axis=1)
    tied = (active == weakest) & (inactive_at_weakest[:, None] > 0)
    wired = (state.wiring.inputs == watched).any(axis=1)
    on = rows[:, watched] != 0
    masks = np.zeros((len(rows), N_KC), dtype=bool)
    np.put_along_axis(masks, codes, values=True, axis=1)
    half = len(rows) // 2
    overlap = (masks[:half] & masks[half : 2 * half]).sum(axis=1) / N_ACTIVE
    return {
        "active_with_zero_drive_share": float((active == 0).mean()),
        "active_chosen_by_tie_break_share": float(tied.mean()),
        "active_wired_to_watched_input_share_when_on": float(wired[codes[on]].mean())
        if on.any()
        else None,
        "watched_input_on_share": float(on.mean()),
        "random_pair_overlap_mean": float(overlap.mean()),
        "distinct_codes_per_distinct_input": len({m.tobytes() for m in np.packbits(masks, axis=1)})
        / len({r.tobytes() for r in rows}),
    }


def saturation_share(variant: DenseVariant, state: DenseVariantState, rows: np.ndarray) -> float:
    """Share of hidden units with |tanh| above SATURATED, before the 1/sqrt(width) scale."""
    return float((np.abs(np.tanh(variant.gained(rows) @ state.hidden_w.T)) > SATURATED).mean())
