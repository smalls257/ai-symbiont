"""Exact binomial and bootstrap arithmetic for the reproduction checks, standard library only."""

import math
import random
import statistics
from collections.abc import Sequence

BOOTSTRAP_DRAWS = 10_000  # the preregs' draw count (Evolve and Core v3 preregs, "10,000 resamples")
TWO_SIDED_TAIL = 0.025  # a 95% two-sided interval leaves 2.5% in each tail
_BISECTION_STEPS = 200


def _log_pmf(successes: int, trials: int, rate: float) -> float:
    """log P(X = successes) for X ~ Binomial(trials, rate), 0 < rate < 1."""
    log_choose = (
        math.lgamma(trials + 1) - math.lgamma(successes + 1) - math.lgamma(trials - successes + 1)
    )
    return log_choose + successes * math.log(rate) + (trials - successes) * math.log1p(-rate)


def _cdf(successes: int, trials: int, rate: float) -> float:
    """P(X <= successes) for X ~ Binomial(trials, rate)."""
    return sum(math.exp(_log_pmf(k, trials, rate)) for k in range(successes + 1))


def clopper_pearson_upper(wrong: int, trials: int) -> float:
    """The exact two-sided 95% upper bound on a rate seen as `wrong` of `trials`.

    Raises ValueError for counts that are not a count of `trials`.
    """
    if not 0 <= wrong <= trials or trials <= 0:
        raise ValueError(f"{wrong} of {trials} is not a count")
    if wrong == trials:
        return 1.0
    if wrong == 0:
        return 1 - TWO_SIDED_TAIL ** (1 / trials)
    low, high = wrong / trials, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2
        if _cdf(wrong, trials, middle) > TWO_SIDED_TAIL:
            low = middle
        else:
            high = middle
    return high


def percentile_interval(means: list[float]) -> tuple[float, float]:
    """The 2.5th and 97.5th percentile of bootstrap means, indexed as the preregs' code does."""
    means.sort()
    draws = len(means)
    return means[int(TWO_SIDED_TAIL * draws)], means[int((1 - TWO_SIDED_TAIL) * draws) - 1]


def bootstrap_mean_interval(values: Sequence[float], seed: int) -> tuple[float, float]:
    """95% percentile bootstrap of the mean, resampling `values` (maps or tasks) whole."""
    rng = random.Random(seed)
    draws = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_DRAWS)]
    return percentile_interval(draws)
