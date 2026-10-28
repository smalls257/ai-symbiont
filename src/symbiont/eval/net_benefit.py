"""Net benefit of warning, the train-chosen threshold and the live-warner rule (T36 prereg)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

NEVER = float("inf")  # no risk reaches it: the learner warns on no step
PRIMARY_COST = 0.5  # prereg ruling: break-even precision 0.33
SENSITIVITY_COSTS = (0.25, 1.0)
COSTS = (PRIMARY_COST, *SENSITIVITY_COSTS)
DENSE_LEARNING_RATES = (0.1, 0.3, 1.0)  # prereg grid, chosen between on TRAIN
TP, FP, FN, TN = range(4)  # columns of a per-task counts array


def net_benefit(totals: np.ndarray, cost: float) -> np.ndarray:
    """Per step, for each row of `totals`: (true warnings - cost * false warnings) / steps."""
    totals = np.atleast_2d(totals)
    result: np.ndarray = (totals[:, TP] - cost * totals[:, FP]) / totals.sum(axis=1)
    return result


@dataclass(frozen=True)
class TrainChoice:
    """The threshold chosen on TRAIN and the net benefit per step it earned there."""

    threshold: float
    net_benefit: float


def _risks_and_labels(
    risks: Sequence[float | None], followed: Sequence[bool]
) -> tuple[np.ndarray, np.ndarray]:
    if len(risks) != len(followed):
        raise ValueError(f"{len(risks)} risks for {len(followed)} labels")
    if not len(risks):
        raise ValueError("cannot choose a threshold on zero train steps")
    if any(r is None for r in risks):
        raise ValueError("a step has no risk score; only learners that report one get a threshold")
    return np.asarray(risks, dtype=np.float64), np.asarray(followed, dtype=bool)


def best_threshold(
    risks: Sequence[float | None], followed: Sequence[bool], cost: float
) -> TrainChoice:
    """The risk threshold with the highest TRAIN net benefit; ties go to the higher one.

    A step warns when its risk is at or above the threshold. If no threshold
    earns more than 0 the choice is `NEVER` with net benefit 0, because never
    warning is always available and fewer warnings win a tie.
    """
    values, labels = _risks_and_labels(risks, followed)
    order = np.argsort(-values, kind="stable")
    ranked, hits = values[order], labels[order]
    group_end = np.append(ranked[1:] != ranked[:-1], True)  # last step of each distinct risk
    gain = np.cumsum(hits) - cost * np.cumsum(~hits)
    gain_per_step = gain[group_end] / len(values)
    best = int(np.argmax(gain_per_step))  # first maximum = highest threshold
    if gain_per_step[best] <= 0:
        return TrainChoice(NEVER, 0.0)
    return TrainChoice(float(ranked[group_end][best]), float(gain_per_step[best]))


def interval(point: float, samples: np.ndarray) -> dict[str, Any]:
    """A value with its 95% percentile interval; NaN draws are counted, not dropped quietly."""
    defined = samples[~np.isnan(samples)]
    low, high = np.percentile(defined, [2.5, 97.5]) if len(defined) else (np.nan, np.nan)

    def clean(number: float) -> float | None:
        return None if np.isnan(number) else float(number)

    return {
        "value": clean(point),
        "ci95_low": clean(low),
        "ci95_high": clean(high),
        "undefined_draws": int(np.isnan(samples).sum()),
    }


def net_benefit_interval(counts: np.ndarray, draws: np.ndarray, cost: float) -> dict[str, Any]:
    """Net benefit per step of per-task `counts`, resampling tasks by `draws`."""
    point = net_benefit(counts.sum(axis=0), cost)[0]
    return interval(float(point), net_benefit(draws @ counts, cost))


def net_benefit_gap(
    counts_a: np.ndarray, counts_b: np.ndarray, draws: np.ndarray, cost: float
) -> dict[str, Any]:
    """Net benefit of `a` minus that of `b` on the same task draws."""
    point = net_benefit(counts_a.sum(axis=0), cost)[0] - net_benefit(counts_b.sum(axis=0), cost)[0]
    sampled = net_benefit(draws @ counts_a, cost) - net_benefit(draws @ counts_b, cost)
    return interval(float(point), sampled)


class Standing(StrEnum):
    """How one learner compares with another, from the interval of their difference."""

    BETTER = "better"
    TIE = "tie"
    WORSE = "worse"


def standing(gap: Mapping[str, Any]) -> Standing:
    """Better if the difference interval is wholly above 0, worse if wholly below."""
    if gap["ci95_low"] > 0:
        return Standing.BETTER
    if gap["ci95_high"] < 0:
        return Standing.WORSE
    return Standing.TIE


class Warner(StrEnum):
    """Who warns live; `NONE` means recall-only."""

    NONE = "none"
    COUNTERS = "counters"
    DENSE = "dense"
    FLY = "fly"


# Tie order of the registered rule: the simplest learner first.
SIMPLEST_FIRST = (Warner.COUNTERS, Warner.DENSE, Warner.FLY)


def live_warner(
    benefit: Mapping[Warner, Mapping[str, Any]], gap_to_counters: Mapping[Warner, Mapping[str, Any]]
) -> Warner:
    """The registered decision rule at c = 0.5.

    `benefit` holds each candidate's net-benefit interval; `gap_to_counters`
    holds the interval of (candidate - counters) for dense and fly. Only a
    candidate whose lower bound is above 0 beats never warning; a learner that
    does not clearly beat counters, when counters also beat never warning,
    loses to counters.
    """
    winners = [w for w in SIMPLEST_FIRST if benefit[w]["ci95_low"] > 0]
    if not winners:
        return Warner.NONE

    def rank(candidate: Warner) -> tuple[float, int]:
        return round(benefit[candidate]["value"], 12), -SIMPLEST_FIRST.index(candidate)

    best = max(winners, key=rank)
    challenger = best is not Warner.COUNTERS and Warner.COUNTERS in winners
    if challenger and standing(gap_to_counters[best]) is not Standing.BETTER:
        return Warner.COUNTERS
    return best
