"""Fit the logistic warner and pick its note threshold under option A. Pure numpy, no files.

Violation prevented: **Paper Tiger**. A threshold picked on the steps the model was fit on, or
by counting every step a score crosses a line, would look good and speak badly. So every step's
risk comes from a model that never saw its repository (grouped folds), notes are spent the way
the service spends them (`symbiont.core.note_rules`: boundary steps, a budget of 2, a 5-step
cooldown), and a threshold is kept only if its notes earn more than they cost. If none does,
the fit raises rather than write a warner that speaks at a loss.

The math repeats T46's `note_cost_logistic` (class-weighted Newton fit, unpenalized intercept),
which lives on an eval branch the live path must not import.
"""

from dataclasses import dataclass

import numpy as np

from symbiont.core.note_rules import may_speak

NEWTON_STEPS = 30
TOLERANCE = 1e-8
# T46 recommendation, the brief's prices for a heads-up: a right note +1, a wrong one -0.25.
NOTE_GAIN = 1.0
FALSE_NOTE_COST = 0.25
# Upper-tail shares of boundary steps that set the threshold grid, dense in the far tail as T46.
GRID_SHARES = tuple(np.geomspace(1e-3, 1.0, 40).tolist())


@dataclass(frozen=True)
class Fit:
    """Standardization and coefficients (intercept first) of one fit."""

    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray


@dataclass(frozen=True)
class Steps:
    """Every step: features, label (trouble within 5 steps), boundary mark, session and fold."""

    features: np.ndarray
    labels: np.ndarray
    boundary: np.ndarray
    session: np.ndarray
    fold: np.ndarray


@dataclass(frozen=True)
class Choice:
    """The chosen threshold and what its notes did on out-of-fold risks."""

    note_at: float
    notes: int
    right: int
    value: float


def class_weights(labels: np.ndarray) -> np.ndarray:
    """Trouble and calm steps get equal total weight; raises when one class is missing."""
    share = labels.mean()
    if share in (0.0, 1.0):
        raise ValueError("a fit needs steps both followed and not followed by trouble")
    return np.where(labels, 0.5 / share, 0.5 / (1.0 - share))


def fit_logistic(features: np.ndarray, labels: np.ndarray, l2: float) -> Fit:
    """Newton steps on the class-weighted log loss plus l2/2 |w|^2; raises if it does not settle."""
    mean, scale = features.mean(axis=0), features.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    design = np.hstack([np.ones((len(features), 1)), (features - mean) / scale])
    weights = class_weights(labels.astype(bool))
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
            return Fit(mean, scale, coef)
    raise ValueError(f"logistic fit with l2={l2} did not settle in {NEWTON_STEPS} Newton steps")


def predict(fit: Fit, features: np.ndarray) -> np.ndarray:
    """Probability of trouble within the label window."""
    logits = fit.coef[0] + ((features - fit.mean) / fit.scale) @ fit.coef[1:]
    result: np.ndarray = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
    return result


def out_of_fold_risks(steps: Steps, l2: float) -> np.ndarray:
    """Each step's risk from a model fit on the other folds only."""
    risks = np.empty(len(steps.labels))
    for fold in np.unique(steps.fold):
        held = steps.fold == fold
        fit = fit_logistic(steps.features[~held], steps.labels[~held], l2)
        risks[held] = predict(fit, steps.features[held])
    return risks


def positions(session: np.ndarray) -> np.ndarray:
    """Each step's index within its session; raises unless sessions are contiguous runs."""
    starts = np.flatnonzero(np.concatenate(([True], session[1:] != session[:-1])))
    if len(np.unique(session)) != len(starts):
        raise ValueError("a session's steps must be contiguous")
    run_start = np.repeat(starts, np.diff(np.append(starts, len(session))))
    return np.arange(len(session)) - run_start


def spoken_steps(steps: Steps, risks: np.ndarray, note_at: float) -> np.ndarray:
    """Indices of the steps that carry a note under option A, spent online per session."""
    where = positions(steps.session)
    spoken: list[int] = []
    said: dict[int, list[int]] = {}
    for row in np.flatnonzero(steps.boundary.astype(bool) & (risks >= note_at)).tolist():
        session_said = said.setdefault(int(steps.session[row]), [])
        if may_speak(session_said, int(where[row])):
            session_said.append(int(where[row]))
            spoken.append(row)
    return np.asarray(spoken, dtype=np.int64)


def score(steps: Steps, risks: np.ndarray, note_at: float) -> Choice:
    """Notes, right notes and net value at one threshold."""
    rows = spoken_steps(steps, risks, note_at)
    right = int(steps.labels[rows].sum())
    wrong = len(rows) - right
    return Choice(note_at, len(rows), right, NOTE_GAIN * right - FALSE_NOTE_COST * wrong)


def choose_threshold(steps: Steps, risks: np.ndarray) -> Choice:
    """The grid threshold with the highest net value; raises when no threshold earns notes."""
    candidates = risks[steps.boundary.astype(bool)]
    if not len(candidates):
        raise ValueError("no boundary step to speak at")
    grid = sorted({float(c) for c in np.quantile(candidates, 1.0 - np.asarray(GRID_SHARES))})
    best = max((score(steps, risks, t) for t in grid), key=lambda choice: choice.value)
    if best.value <= 0:
        raise ValueError("no threshold earns notes: every setting costs more than it gains")
    return best


def auc(labels: np.ndarray, risks: np.ndarray) -> float:
    """Area under the ROC curve, ties counted half (Mann-Whitney)."""
    _, inverse, counts = np.unique(risks, return_inverse=True, return_counts=True)
    average_rank = np.cumsum(counts) - (counts - 1) / 2
    ranks = average_rank[inverse]
    positives = labels.astype(bool)
    n_pos, n_neg = positives.sum(), (~positives).sum()
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))
