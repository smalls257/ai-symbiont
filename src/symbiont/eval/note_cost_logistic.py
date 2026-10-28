"""A plain classifier row for T46: batch logistic regression on the learners' per-step features.

A reference baseline: it fits the raw features in one batch with an L2 penalty and class weights,
unlike DenseNet's online readout. Risks are out of sample: for an outer fold, other folds' steps
get risks from inner models that never saw their fold. Pure numpy.
"""

from dataclasses import dataclass

import numpy as np

L2_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)  # penalty on the summed weighted log loss
NEWTON_STEPS = 30
TOLERANCE = 1e-8


@dataclass(frozen=True)
class Logistic:
    """Standardization and coefficients of one fit."""

    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray  # intercept first


def _design(features: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Standardized features with an intercept column."""
    standard = (features - mean) / scale
    return np.hstack([np.ones((len(standard), 1)), standard])


def class_weights(labels: np.ndarray) -> np.ndarray:
    """Weights that give trouble and calm steps equal total weight, summing to the step count."""
    share = labels.mean()
    if share in (0.0, 1.0):
        raise ValueError("a fit needs steps both followed and not followed by trouble")
    return np.where(labels, 0.5 / share, 0.5 / (1.0 - share))


def fit_logistic(features: np.ndarray, labels: np.ndarray, l2: float) -> Logistic:
    """Newton steps on the class-weighted L2 log loss; raises if they do not settle."""
    mean, scale = features.mean(axis=0), features.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    design, weights = _design(features, mean, scale), class_weights(labels.astype(bool))
    penalty = np.full(design.shape[1], l2)
    penalty[0] = 0.0
    coef = np.zeros(design.shape[1])
    for _ in range(NEWTON_STEPS):
        prob = 1.0 / (1.0 + np.exp(-np.clip(design @ coef, -30, 30)))
        gradient = design.T @ (weights * (prob - labels)) + penalty * coef
        curvature = (design * (weights * prob * (1 - prob))[:, None]).T @ design
        step = np.linalg.solve(curvature + np.diag(penalty) + 1e-9 * np.eye(len(coef)), gradient)
        coef -= step
        if np.max(np.abs(step)) < TOLERANCE:
            return Logistic(mean, scale, coef)
    raise ValueError(f"logistic fit with l2={l2} did not settle in {NEWTON_STEPS} Newton steps")


def predict(model: Logistic, features: np.ndarray) -> np.ndarray:
    """Probability of trouble within the label window, under the class-weighted fit."""
    result: np.ndarray = 1.0 / (
        1.0 + np.exp(-np.clip(_design(features, model.mean, model.scale) @ model.coef, -30, 30))
    )
    return result


@dataclass(frozen=True)
class Steps:
    """Every TRAIN step: its features, label and task fold."""

    features: np.ndarray
    labels: np.ndarray
    fold: np.ndarray


def outer_fold_risks(
    steps: Steps, outer: int, l2: float, fit_mask: np.ndarray | None = None
) -> np.ndarray:
    """Out-of-sample risk of each step for one outer fold; `fit_mask` limits fitting."""
    allowed = np.ones(len(steps.labels), dtype=bool) if fit_mask is None else fit_mask
    risks = np.empty(len(steps.labels))
    for fold in np.unique(steps.fold):
        held = steps.fold == fold
        fit_on = (steps.fold != fold) & (steps.fold != outer) if fold != outer else ~held
        fit_on &= allowed
        model = fit_logistic(steps.features[fit_on], steps.labels[fit_on], l2)
        risks[held] = predict(model, steps.features[held])
    return risks


def out_of_fold_risks(steps: Steps, l2: float, always: Steps | None = None) -> np.ndarray:
    """Each step's risk from a model fit on the other folds (plus `always`, e.g. a pool)."""
    risks = np.empty(len(steps.labels))
    for fold in np.unique(steps.fold):
        held = steps.fold == fold
        features, labels = steps.features[~held], steps.labels[~held]
        if always is not None:
            features = np.vstack([always.features, features])
            labels = np.concatenate([always.labels, labels])
        risks[held] = predict(fit_logistic(features, labels, l2), steps.features[held])
    return risks
