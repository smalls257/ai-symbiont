"""The pre-registered live-learner rule and the task-level bootstrap behind it.

Violation prevented: **Paper Tiger**. The choice between the fly and the plain
counters is a rule on two numbers (`live_learner`) fixed in the prereg, so a
tie or a lucky wiring cannot be argued into a win after the numbers are seen.
Pure: scores in, verdict out.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from symbiont.eval.offline import OfflineScores

MARGIN = 0.02


class GapInterval(NamedTuple):
    """A point estimate of the AUROC gap with its 95% percentile interval."""

    gap: float
    low: float
    high: float


@dataclass(frozen=True)
class Verdict:
    """Which learner goes live under the registered rule, and the gap behind it."""

    live: str  # "fly" or "counters"
    gap: float
    ci_low: float
    ci_high: float


def bootstrap_auroc_gap(
    flies: Sequence[OfflineScores], counters: OfflineScores, *, seed: int, n_boot: int = 2000
) -> GapInterval:
    """Gap (mean fly AUROC over wiring seeds - counters AUROC) with its 95% interval.

    The interval comes from resampling whole tasks (a task's attempts are not
    independent). Every wiring seed sees the same steps, so averaging the
    per-task counts across seeds is the same as averaging their AUROCs.
    """
    if not flies:
        raise ValueError("no fly runs to compare")
    shape = [(s.task_id, s.followed) for s in counters.per_session]
    if any([(s.task_id, s.followed) for s in fly.per_session] != shape for fly in flies):
        raise ValueError("fly and counters were not replayed on the same sessions")
    tasks = sorted({s.task_id for s in counters.per_session})
    fly_counts = sum(_counts_by_task(fly, tasks) for fly in flies) / len(flies)
    counter_counts = _counts_by_task(counters, tasks)
    draws = np.random.default_rng(seed).multinomial(
        len(tasks), [1 / len(tasks)] * len(tasks), size=n_boot
    )
    gaps = _rate(draws @ fly_counts) - _rate(draws @ counter_counts)
    low, high = np.percentile(gaps, [2.5, 97.5])
    point = sum(fly.auroc for fly in flies) / len(flies) - counters.auroc
    return GapInterval(point, float(low), float(high))


def bootstrap_auroc_interval(
    runs: Sequence[OfflineScores], *, seed: int, n_boot: int = 2000
) -> tuple[float, float, float]:
    """Descriptive, not part of the rule: one row's own balanced accuracy and interval.

    The mean is over `runs` (the wiring seeds of a fly row), with the same
    task-level percentile bootstrap as the gap. The same seed gives the same
    task draws as `bootstrap_auroc_gap`.
    """
    if not runs:
        raise ValueError("no runs to summarize")
    tasks = sorted({s.task_id for s in runs[0].per_session})
    counts = sum(_counts_by_task(run, tasks) for run in runs) / len(runs)
    draws = np.random.default_rng(seed).multinomial(
        len(tasks), [1 / len(tasks)] * len(tasks), size=n_boot
    )
    low, high = np.percentile(_rate(draws @ counts), [2.5, 97.5])
    return sum(run.auroc for run in runs) / len(runs), float(low), float(high)


def _counts_by_task(scores: OfflineScores, tasks: list[str]) -> np.ndarray:
    """Per task: positives, negatives, true positives, true negatives."""
    index = {t: i for i, t in enumerate(tasks)}
    counts = np.zeros((len(tasks), 4))
    for s in scores.per_session:
        for followed, flagged in zip(s.followed, s.flagged, strict=True):
            counts[index[s.task_id]] += (
                followed,
                not followed,
                followed and flagged,
                (not followed) and not flagged,
            )
    return counts


def _rate(totals: np.ndarray) -> np.ndarray:
    if (totals[:, 0] == 0).any() or (totals[:, 1] == 0).any():
        raise ValueError("a bootstrap sample had no positive or no negative steps; too few tasks")
    rates: np.ndarray = (totals[:, 2] / totals[:, 0] + totals[:, 3] / totals[:, 1]) / 2
    return rates


def live_learner(gap: float, ci_low: float) -> str:
    """The registered rule on its two numbers.

    Fly only if the gap reaches MARGIN and the interval's lower bound is above
    0. The gap is rounded to 12 places so float fuzz cannot decide a gap of
    exactly MARGIN.
    """
    return "fly" if round(gap, 12) >= MARGIN and ci_low > 0 else "counters"


def fly_default(flies: Sequence[OfflineScores], counters: OfflineScores, *, seed: int) -> Verdict:
    """Pre-registered rule, on the seed-averaged fly scores (see `live_learner`)."""
    gap, low, high = bootstrap_auroc_gap(flies, counters, seed=seed)
    return Verdict(live_learner(gap, low), gap, low, high)
