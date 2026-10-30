"""Plug round 4's primary statistics: per-repo coverage, the clustered bootstrap, verdicts, claim.

Why: the primary metric is the per-repo mean of coverage over each repository's positive items,
and repositories (not items) are the unit that varies, so the interval resamples repositories.
Wrong pick is pooled over all primary items, negatives included. Pure: items and choices in.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from plug_judge import Choice
from plug_situation import Item

RESAMPLES, SEED = 10_000, 0
WIN_GAIN = 0.05  # the mean coverage gain a "better" reading needs
WRONG_LIMIT, WRONG_BOUND_LIMIT = 0.05, 0.10


@dataclass(frozen=True)
class RepoTable:
    """Per repository: positive items, right answers on them, all items, wrong answers on all."""

    repos: tuple[str, ...]
    positives: np.ndarray
    right: np.ndarray
    items: np.ndarray
    wrong: np.ndarray
    answered: np.ndarray


def repo_table(items: Sequence[Item], repo_of: dict, choices: Sequence[Choice]) -> RepoTable:
    """The per-repository counts the primary metric and its bootstrap use."""
    chosen = {c.item_id: c.lesson_id for c in choices}
    repos = sorted({repo_of[i.item_id] for i in items})
    rows = {r: [0, 0, 0, 0, 0] for r in repos}
    for item in items:
        row, answer = rows[repo_of[item.item_id]], chosen[item.item_id]
        right = item.applies is not None and answer == item.applies.lesson_id
        row[0] += item.applies is not None
        row[1] += right
        row[2] += 1
        row[3] += answer is not None and not right
        row[4] += answer is not None
    grid = np.array([rows[r] for r in repos], dtype=float)
    return RepoTable(tuple(repos), *grid.T)


def coverage(table: RepoTable, weights: np.ndarray | None = None) -> float:
    """The mean over repositories with a positive item of right / positives."""
    use = table.positives > 0
    share = np.where(use, table.right / np.maximum(table.positives, 1), 0.0)
    weight = (np.ones(len(share)) if weights is None else weights) * use
    return float((share * weight).sum() / weight.sum())


def pooled_wrong(table: RepoTable) -> float:
    """Wrong answers over all items, negatives included."""
    return float(table.wrong.sum() / table.items.sum())


def pooled_rates(table: RepoTable) -> dict:
    """Pooled wrong pick, precision and answered count."""
    answered = float(table.answered.sum())
    return {
        "wrong_pick": round(pooled_wrong(table), 4),
        "precision": round(float(table.right.sum()) / answered, 4) if answered else None,
        "answered": int(answered),
    }


def bootstrap(rule: RepoTable, alone: RepoTable) -> dict:
    """Resample repositories: the coverage gain and the rule's wrong pick."""
    rng = np.random.default_rng(SEED)
    count = len(rule.repos)
    draws = rng.integers(0, count, size=(RESAMPLES, count))
    weights = np.apply_along_axis(lambda row: np.bincount(row, minlength=count), 1, draws)
    gains, wrongs = [], []
    for weight in weights:
        gains.append(coverage(rule, weight) - coverage(alone, weight))
        wrongs.append((rule.wrong * weight).sum() / (rule.items * weight).sum())
    return {
        "gain_mean": float(np.mean(gains)),
        "gain_low": float(np.quantile(gains, 0.025)),
        "gain_high": float(np.quantile(gains, 0.975)),
        "wrong_high": float(np.quantile(wrongs, 0.975)),
    }


def verdict(gain: float, low: float, high: float) -> str:
    """better / worse / tie, by the decision rule."""
    if low > 0 and gain >= WIN_GAIN:
        return "better"
    return "worse" if high < 0 else "tie"


def safety(wrong: float, upper: float) -> str:
    """Whether wrong pick and its clustered bound meet the limits."""
    ok = wrong <= WRONG_LIMIT and upper <= WRONG_BOUND_LIMIT
    return "safe" if ok else "safety not shown"
