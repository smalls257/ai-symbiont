"""PLUG-AGENT-2 inference over branch points: a sign-flip test on the mean and a BCa interval.

Both take the per-point paired differences (forced minus none); the unit is the point. Seeds and
counts are the prereg's (100,000 flips, 10,000 resamples, seed 0). Pure.
"""

import random
from collections.abc import Sequence
from statistics import NormalDist, fmean

FLIPS = 100_000
RESAMPLES = 10_000
EXACT_UP_TO = 16  # at most 2**16 sign patterns are enumerated; more points use random flips


def sign_flip_p(diffs: Sequence[float], flips: int = FLIPS, seed: int = 0) -> float:
    """Two-sided p of |mean| under random sign changes of the per-point differences."""
    observed = abs(fmean(diffs))
    if observed == 0:
        return 1.0
    count = len(diffs)
    if count <= EXACT_UP_TO:
        patterns = range(2**count)
        extreme = sum(
            abs(fmean(d if not (mask >> i) & 1 else -d for i, d in enumerate(diffs)))
            >= observed - 1e-12
            for mask in patterns
        )
        return extreme / 2**count
    rng = random.Random(seed)
    extreme = sum(
        abs(fmean(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - 1e-12
        for _ in range(flips)
    )
    return (extreme + 1) / (flips + 1)


def bca_interval(
    diffs: Sequence[float], resamples: int = RESAMPLES, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    """BCa interval for the mean: bias correction from the bootstrap, acceleration by jackknife."""
    count, theta = len(diffs), fmean(diffs)
    rng = random.Random(seed)
    means = sorted(fmean(rng.choices(diffs, k=count)) for _ in range(resamples))
    normal = NormalDist()
    below = sum(m < theta for m in means) / resamples
    z0 = normal.inv_cdf(min(max(below, 1 / resamples), 1 - 1 / resamples))
    jack = [fmean(diffs[:i] + diffs[i + 1 :]) for i in range(count)]
    center = fmean(jack)
    spread = sum((center - j) ** 2 for j in jack)
    skew = sum((center - j) ** 3 for j in jack)
    accel = skew / (6 * spread**1.5) if spread else 0.0
    return tuple(means[_index(z0, accel, q, normal, resamples)] for q in (alpha / 2, 1 - alpha / 2))


def _index(z0: float, accel: float, quantile: float, normal: NormalDist, resamples: int) -> int:
    quantile_z = normal.inv_cdf(quantile)
    adjusted = normal.cdf(z0 + (z0 + quantile_z) / (1 - accel * (z0 + quantile_z)))
    return min(max(int(adjusted * resamples), 0), resamples - 1)


def cluster_means(values: Sequence[float], clusters: Sequence[str]) -> list[float]:
    """Mean per cluster (for the sensitivity analysis clustered by (repository, key))."""
    groups: dict[str, list[float]] = {}
    for value, cluster in zip(values, clusters, strict=True):
        groups.setdefault(cluster, []).append(value)
    return [fmean(group) for _, group in sorted(groups.items())]
