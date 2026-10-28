"""Input gain control: each of the 86 inputs centered and scaled before the expansion layer.

Two inputs are log line counts (up to about 8) and the rest 0/1 flags, so unweighted cells wired
to the counts win the top-5% race and the code says little else (T47 [measured]). Projection
neurons normalize and saturate [established]; here the mean, the gain 1/spread and a cap of
`PN_CEILING` spreads are fit on training repositories only, then fixed. Without the cap a rare
flag takes over.
"""

from dataclasses import dataclass

import numpy as np

PN_CEILING = 3.0  # spreads; a flag on 10% of steps reaches 3.0, so common flags are not cut


@dataclass(frozen=True)
class InputGain:
    """Per-input background and gain; `apply` maps raw features to normalized ones."""

    background: np.ndarray  # (n_inputs,) mean of each input on the training steps
    gain: np.ndarray  # (n_inputs,) one over its spread; 1 for an input that never varied

    def apply(self, rows: np.ndarray) -> np.ndarray:
        """Normalized, capped copy of one feature vector or a (steps, inputs) matrix."""
        centered = (np.asarray(rows, dtype=np.float64) - self.background) * self.gain
        result: np.ndarray = np.clip(centered, -PN_CEILING, PN_CEILING)
        return result


def fit_input_gain(rows: np.ndarray) -> InputGain:
    """Background and gain from training steps (rows are steps).

    Raises ValueError for an empty or one-dimensional matrix: a gain fit on nothing would
    pass every input through unchanged and hide that it was never fit.
    """
    rows = np.asarray(rows, dtype=np.float64)
    if rows.ndim != 2 or len(rows) == 0:
        raise ValueError(f"input gain needs a non-empty (steps, inputs) matrix, got {rows.shape}")
    spread = rows.std(axis=0)
    gain = np.where(spread > 0, 1.0 / np.where(spread > 0, spread, 1.0), 1.0)
    return InputGain(background=rows.mean(axis=0), gain=gain)
