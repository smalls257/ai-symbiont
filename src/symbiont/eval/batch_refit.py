"""R2 refits for batch readouts: a logistic fit pulled toward the shipped weights (T47).

Violation prevented: **Silent Fallback**. A project's first sessions may hold no trouble at all;
a plain refit then either fails or learns "never warn". Pulling the fit toward the shipped
weights (a Gaussian prior centered on them) keeps every refit defined, so no refit is skipped
quietly, and the weights move only as far as the project's own steps justify.

Used for the batch logistic regression (its standardized features), for a DenseNet variant's
readout (over its fixed hidden layer), and to turn a DenseNet variant into a `TanhNet` whose
hidden layer backprop may then refit.
"""

from dataclasses import replace

import numpy as np

from symbiont.core.dense_variants import DenseVariant, DenseVariantState, ReadoutInput
from symbiont.core.input_gain import InputGain
from symbiont.eval.note_cost_logistic import Logistic
from symbiont.eval.tanh_net import TanhNet

NEWTON_STEPS = 25
REFIT_PRIOR = 10.0  # not tuned; the shipped T46 classifier used 1000 on 80 repositories of steps


def map_logistic(
    design: np.ndarray, labels: np.ndarray, weights: np.ndarray, prior: np.ndarray, strength: float
) -> np.ndarray:
    """Newton on the weighted log loss plus strength/2 times |coef - prior|^2.

    Every coefficient, the intercept too, is pulled toward the prior; with strength > 0 the
    problem is strictly convex, so it always settles. Raises ValueError for strength <= 0.
    """
    if not strength > 0:
        raise ValueError(f"the prior strength must be positive, got {strength}")
    coef = prior.copy()
    for _ in range(NEWTON_STEPS):
        prob = 1.0 / (1.0 + np.exp(-np.clip(design @ coef, -30, 30)))
        grad = design.T @ (weights * (prob - labels)) + strength * (coef - prior)
        curvature = (design * (weights * prob * (1 - prob))[:, None]).T @ design
        step = np.linalg.solve(curvature + strength * np.eye(len(coef)), grad)
        coef = coef - step
        if np.max(np.abs(step)) < 1e-8:
            break
    return coef


def trouble_weights(labels: np.ndarray, trouble_share: float) -> np.ndarray:
    """Class weights fixed by the training trouble share, not by the few project steps."""
    return np.where(labels, 0.5 / trouble_share, 0.5 / (1.0 - trouble_share))


class LogisticScorer:
    """The batch classifier as a `regime_replay.Scorer`; the state is its coefficients."""

    def __init__(self, model: Logistic) -> None:
        """Keep the shipped model's standardization: refits move only the coefficients."""
        self._mean, self._scale = model.mean, model.scale

    def encode(self, rows: np.ndarray, coef: np.ndarray) -> np.ndarray:
        """Intercept column and standardized features."""
        standard = (np.atleast_2d(rows) - self._mean) / self._scale
        return np.hstack([np.ones((len(standard), 1)), standard])

    def step_risks(self, encoded: np.ndarray, coef: np.ndarray) -> np.ndarray:
        """Probability of trouble under the class-weighted fit."""
        result: np.ndarray = 1.0 / (1.0 + np.exp(-np.clip(encoded @ coef, -30, 30)))
        return result


def refit_readout(
    variant: DenseVariant, shipped: DenseVariantState, encoded: np.ndarray, labels: np.ndarray
) -> DenseVariantState:
    """A DenseNet variant's readout and bias refit in batch, pulled toward the shipped ones."""
    design = np.hstack([encoded, np.ones((len(encoded), 1))])
    weights = np.where(labels, variant.trouble_weight, 1.0)
    prior = np.append(shipped.readout, shipped.bias)
    coef = map_logistic(design, labels.astype(float), weights, prior, REFIT_PRIOR)
    return replace(shipped, readout=coef[:-1], bias=float(coef[-1]))


def dense_as_net(variant: DenseVariant, state: DenseVariantState) -> TanhNet:
    """The same function as a `TanhNet`, so backprop can refit its hidden layer too."""
    width = state.hidden_w.shape[1]
    gain = variant.gain or InputGain(background=np.zeros(width), gain=np.ones(width))
    hidden = variant.hidden
    skip = (
        state.readout[hidden:]
        if variant.readout_input == ReadoutInput.HIDDEN_AND_INPUTS
        else np.zeros(width)
    )
    return TanhNet(
        gain=gain,
        w_in=state.hidden_w.copy(),
        b_in=np.zeros(hidden),
        w_out=state.readout[:hidden] / np.sqrt(hidden),
        w_skip=np.array(skip, dtype=np.float64),
        bias=state.bias,
    )
