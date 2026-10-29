"""Does the fitted logistic warner rank annotated wrong steps above the rest? Exploratory only.

On 31 coding traces an AUC can look like a finding, so each comes with its counts, a trace-level
bootstrap interval, the step-position reference, the base rate and the note-at-every-boundary
floor, plus the warner's score on its own training label (mined trouble) on the same steps.
Risks come from the weights fitted on the public OpenHands pool; nothing is refitted. Pure numpy.
"""

from dataclasses import dataclass

import numpy as np
from warner_fit import Steps, auc, spoken_steps

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261029  # the T36/T46 split seed, reused so reruns agree


@dataclass(frozen=True)
class StepTable:
    """Every scored step: risk, boundary mark, session number, step position, named labels."""

    risks: np.ndarray
    boundary: np.ndarray
    session: np.ndarray
    position: np.ndarray
    labels: dict[str, np.ndarray]


def label_scores(table: StepTable, label: str, note_at: float) -> dict[str, object]:
    """Ranking and note precision of one label, with its base rate and floor beside it."""
    truth = table.labels[label].astype(bool)
    spoken = _spoken(table, truth, note_at)
    flagged = table.risks >= note_at
    return {
        "steps": int(len(truth)),
        "positives": int(truth.sum()),
        "sessions_with_positive": int(len(np.unique(table.session[truth]))),
        "base_rate": _ratio(int(truth.sum()), len(truth)),
        "auc": _auc_or_none(truth, table.risks),
        "auc_ci95": bootstrap_auc(table, truth),
        # Reference: the step's position alone. Risk grows along a session, so a label that
        # sits early (or late) in traces is ranked by position before any feature matters.
        "auc_step_position_reference": _auc_or_none(truth, table.position.astype(float)),
        "operating_point": {
            "notes": int(len(spoken)),
            "right_notes": int(truth[spoken].sum()),
            "precision": _ratio(int(truth[spoken].sum()), len(spoken)),
        },
        "risk_at_or_above_note_at": {
            "steps": int(flagged.sum()),
            "right": int(truth[flagged].sum()),
            "precision": _ratio(int(truth[flagged].sum()), int(flagged.sum())),
        },
        "floor_every_boundary_precision": _ratio(
            int(truth[table.boundary].sum()), int(table.boundary.sum())
        ),
    }


def _spoken(table: StepTable, truth: np.ndarray, note_at: float) -> np.ndarray:
    """Rows the service would speak at (option A: boundary, threshold, budget, cooldown)."""
    size = len(truth)
    steps = Steps(
        np.zeros((size, 1)), truth, table.boundary, table.session, np.zeros(size, dtype=int)
    )
    return spoken_steps(steps, table.risks, note_at)


def _ratio(part: int, whole: int) -> float | None:
    """part / whole rounded, or None when there is nothing to divide by."""
    return round(part / whole, 4) if whole else None


def _auc_or_none(truth: np.ndarray, risks: np.ndarray) -> float | None:
    """AUC, or None when one class is missing (undefined, never reported as 0.5)."""
    if truth.all() or not truth.any():
        return None
    return round(auc(truth, risks), 4)


def bootstrap_auc(table: StepTable, truth: np.ndarray) -> dict[str, object]:
    """95% percentile interval of the AUC over traces drawn with replacement."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    sessions = np.unique(table.session)
    rows_of = {s: np.flatnonzero(table.session == s) for s in sessions.tolist()}
    draws, undefined = [], 0
    for _ in range(BOOTSTRAP_DRAWS):
        rows = np.concatenate([rows_of[s] for s in rng.choice(sessions, len(sessions)).tolist()])
        value = _auc_or_none(truth[rows], table.risks[rows])
        undefined += value is None
        if value is not None:
            draws.append(value)
    if not draws:
        return {"low": None, "high": None, "undefined_draws": undefined}
    low, high = np.percentile(draws, [2.5, 97.5])
    return {
        "low": round(float(low), 4),
        "high": round(float(high), 4),
        "undefined_draws": undefined,
    }


def restricted(table: StepTable, keep: np.ndarray) -> StepTable:
    """The same table on the kept rows only."""
    return StepTable(
        table.risks[keep],
        table.boundary[keep],
        table.session[keep],
        table.position[keep],
        {name: values[keep] for name, values in table.labels.items()},
    )
