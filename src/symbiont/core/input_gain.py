"""Input gain control: each of the 86 inputs centered and scaled before the expansion layer.

Violation prevented: **Paper Tiger**. The fly's Kenyon cells sum their inputs unweighted. Two
of the 86 inputs are log line counts (up to about 8) while the rest are 0/1 flags, so on most
steps the cells wired to the line counts win the top-5% race whatever else is true, and the
circuit codes "an edit happened earlier" and little else (T47 [measured]). Learning on such a
code passes its tests and helps nobody. A random tanh layer saturates on the same inputs.

Biology: projection neurons normalize their odor responses by the total input to the antennal
lobe (divisive gain control, Olsen, Bhandawat and Wilson 2010) and adapt to steady background
input [established], and their responses saturate (the normalization is a saturating
ratio) [established]. Here the background is the mean of each input, the gain one over its
spread and the response is capped at `PN_CEILING` spreads, all fit on training repositories
only, then fixed: a new project never moves them. Without the cap a rare flag (a file that
failed five times, on 0.002% of training steps) is scaled to about 200 and takes over the code
and the dense readout as the line counts did (T47 [measured]).
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
