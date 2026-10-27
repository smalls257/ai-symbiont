"""Precision, recall and net benefit at a warning budget (Task 14c, exploratory).

Violation prevented: **Paper Tiger**. Balanced accuracy let each learner pick
its own warning rate, and the fly picked "most steps". Here every learner is
held to the same share of steps (the budget), and a wrong warning costs
something: net benefit per 100 steps is TP - c * FP. The analysis is fixed in
`prereg/2026-10-28-warning-budget-exploratory.md` and cannot change the G6
verdict.

Second guard, **Silent Fallback**: precision with no warnings is undefined,
not 0 and not 1. It is reported as None, and bootstrap draws that hit it are
counted, never dropped quietly. A step with no risk score raises.

Everything is a function of counts per task, so the bootstrap resamples whole
tasks (a task's attempts are not independent) with the same multinomial draws
for every row, which keeps differences between rows paired.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.core.slot import Decider, Decision, Outcome, Situation
from symbiont.eval.offline import OfflineScores

BUDGETS = (0.10, 0.15, 0.20)
FALSE_ALARM_COSTS = (0.5, 1.0, 2.0)  # c: one wrong warning costs c right ones (an assumption)
N_BOOT = 2000
PER_STEPS = 100
TP, FP, FN, TN = range(4)  # columns of a counts array


@dataclass(frozen=True)
class RiskTrace:
    """One replayed session: the label and the risk at every step."""

    task_id: str
    followed: tuple[bool, ...]
    risk: tuple[float | None, ...]


class RiskRecorder:
    """A Decider that remembers each decision's risk in step order.

    Wraps a learner for a replay without touching the replay or the learner:
    `replay` decides steps one after another, so the recorded list lines up
    with the flat sequence of scored steps. It only observes.
    """

    def __init__(self, inner: Decider) -> None:
        self._inner = inner
        self.name = inner.name
        self.risks: list[float | None] = []

    def initial_state(self, seed: int) -> Any:
        """The wrapped learner's own fresh state."""
        return self._inner.initial_state(seed)

    def decide(self, x: np.ndarray, situation: Situation, state: Any) -> Decision:
        """Decide as the wrapped learner does, noting the risk."""
        decision = self._inner.decide(x, situation, state)
        self.risks.append(decision.risk)
        return decision

    def learn(self, x: np.ndarray, outcome: Outcome, state: Any) -> Any:
        """Learn as the wrapped learner does."""
        return self._inner.learn(x, outcome, state)


def risk_traces(scores: OfflineScores, recorder: RiskRecorder) -> tuple[RiskTrace, ...]:
    """Pair each scored session with the risks recorded while it was decided."""
    if len(recorder.risks) != scores.n_steps:
        raise ValueError(
            f"recorded {len(recorder.risks)} risks for {scores.n_steps} scored steps; "
            "use a fresh RiskRecorder for each replay call"
        )
    traces, start = [], 0
    for session in scores.per_session:
        stop = start + len(session.followed)
        traces.append(
            RiskTrace(session.task_id, session.followed, tuple(recorder.risks[start:stop]))
        )
        start = stop
    return tuple(traces)


def flat_risks(traces: Sequence[RiskTrace]) -> list[float | None]:
    """Every step's risk, in replay order (the TRAIN input to `calibrate_budget`)."""
    return [risk for trace in traces for risk in trace.risk]


def counts_by_task(
    traces: Sequence[RiskTrace], threshold: float, tasks: Sequence[str]
) -> np.ndarray:
    """Per task: true positives, false positives, misses and true negatives."""
    index = {task: i for i, task in enumerate(tasks)}
    counts = np.zeros((len(tasks), 4))
    for trace in traces:
        if any(risk is None for risk in trace.risk):
            raise ValueError(f"task {trace.task_id} has a step with no risk score")
        risks = [risk for risk in trace.risk if risk is not None]
        for followed, risk in zip(trace.followed, risks, strict=True):
            flagged = risk >= threshold
            column = (TP if followed else FP) if flagged else (FN if followed else TN)
            counts[index[trace.task_id], column] += 1
    return counts


def metrics_of(totals: np.ndarray) -> dict[str, np.ndarray]:
    """Precision, recall, flag rate and net benefit for each row of `totals`.

    Precision is NaN where nothing was flagged, recall where no step was
    followed by trouble: undefined, never 0 or 1.
    """
    totals = np.atleast_2d(totals)
    tp, fp, fn = totals[:, TP], totals[:, FP], totals[:, FN]
    steps = totals.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        metrics = {
            "precision": np.where(tp + fp > 0, tp / (tp + fp), np.nan),
            "recall": np.where(tp + fn > 0, tp / (tp + fn), np.nan),
            "flag_rate": (tp + fp) / steps,
        }
        for cost in FALSE_ALARM_COSTS:
            metrics[f"net_benefit_per_{PER_STEPS}_c{cost:g}"] = PER_STEPS * (tp - cost * fp) / steps
    return metrics


def bootstrap_draws(n_tasks: int, *, seed: int, n_boot: int = N_BOOT) -> np.ndarray:
    """How many times each task is drawn in each bootstrap sample (same scheme as G6)."""
    probabilities = [1 / n_tasks] * n_tasks
    return np.random.default_rng(seed).multinomial(n_tasks, probabilities, size=n_boot)


def _interval(point: float, samples: np.ndarray) -> dict[str, Any]:
    defined = samples[~np.isnan(samples)]
    low, high = np.percentile(defined, [2.5, 97.5]) if len(defined) else (np.nan, np.nan)
    return {
        "value": None if np.isnan(point) else float(point),
        "ci95_low": None if np.isnan(low) else float(low),
        "ci95_high": None if np.isnan(high) else float(high),
        "undefined_draws": int(np.isnan(samples).sum()),
    }


def budget_row(counts: np.ndarray, draws: np.ndarray) -> dict[str, dict[str, Any]]:
    """Each metric with its task-level 95% percentile interval."""
    point = metrics_of(counts.sum(axis=0))
    sampled = metrics_of(draws @ counts)
    return {name: _interval(point[name][0], sampled[name]) for name in point}


def difference_row(
    counts_a: np.ndarray, counts_b: np.ndarray, draws: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Metric of `a` minus metric of `b`, on the same task draws."""
    point_a, point_b = metrics_of(counts_a.sum(axis=0)), metrics_of(counts_b.sum(axis=0))
    sampled_a, sampled_b = metrics_of(draws @ counts_a), metrics_of(draws @ counts_b)
    return {
        name: _interval(point_a[name][0] - point_b[name][0], sampled_a[name] - sampled_b[name])
        for name in point_a
    }
