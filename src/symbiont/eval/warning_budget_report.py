"""Assemble the exploratory warning-budget results (Task 14c).

Violation prevented: **Paper Tiger** and **Silent Fallback**. The report
cannot be built without the counters beside the fly rows and a warn-on-every-
step floor under both, and every threshold comes from TRAIN risks only
(`operating_point`); test risks are only ever counted against it. Pure
functions of traces: no file, clock or network, so the run script only loads
data and writes the result (**Infected Core** guard).

Output is counts, ids and labels: tables are lists of short row strings so no
long text blob lands in the results file.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.core.warning_budget import calibrate_budget
from symbiont.eval.warning_budget_metrics import (
    BUDGETS,
    FALSE_ALARM_COSTS,
    N_BOOT,
    PER_STEPS,
    RiskTrace,
    bootstrap_draws,
    budget_row,
    counts_by_task,
    difference_row,
    flat_risks,
)

FLOOR_ARM = "warn on every step"
TEXT_COLUMNS = (("precision", "precision"), ("recall", "recall"), ("flags", "flag_rate"))
Intervals = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ArmTraces:
    """Risk traces of one learner: the online TRAIN replay and the TEST continuation."""

    train: tuple[RiskTrace, ...]
    test: tuple[RiskTrace, ...]


@dataclass(frozen=True)
class OperatingPoint:
    """The TRAIN-calibrated threshold, its TRAIN flag rate and the TEST counts."""

    threshold: float
    train_flag_rate: float
    counts: np.ndarray


def operating_point(arm: ArmTraces, budget: float, tasks: Sequence[str]) -> OperatingPoint:
    """Calibrate on `arm.train` only, then count the test steps at that threshold."""
    train_risks = flat_risks(arm.train)
    threshold = calibrate_budget(train_risks, budget)
    train_rate = float(np.mean(np.asarray(train_risks) >= threshold))
    return OperatingPoint(threshold, train_rate, counts_by_task(arm.test, threshold, tasks))


def _row(
    arm: str, role: str, budget: float | None, metrics: Intervals, **extra: Any
) -> dict[str, Any]:
    return {
        "arm": arm,
        "role": role,
        "split": "test",
        "budget": budget,
        **extra,
        "metrics": metrics,
    }


def _arm_rows(
    name: str, role: str, points: Sequence[OperatingPoint], budget: float, draws: np.ndarray
) -> dict[str, Any]:
    counts = np.mean([p.counts for p in points], axis=0)
    return _row(
        name,
        role,
        budget,
        budget_row(counts, draws),
        thresholds=[p.threshold for p in points],
        train_flag_rate=float(np.mean([p.train_flag_rate for p in points])),
    )


def _per_task_lines(tasks: Sequence[str], counts: np.ndarray) -> list[str]:
    return [
        f"{task},{','.join(str(int(c)) for c in row)}"
        for task, row in zip(tasks, counts, strict=True)
    ]


def _show(metrics: Intervals, name: str, digits: int = 3) -> str:
    value = metrics[name]
    if value["value"] is None:
        return "undefined"
    low, high = value["ci95_low"], value["ci95_high"]
    return f"{value['value']:.{digits}f} [{low:.{digits}f}, {high:.{digits}f}]"


def _text_rows(row: Mapping[str, Any]) -> list[str]:
    metrics, head = row["metrics"], f"{row['arm']} | budget {row['budget']}"
    benefit = " | ".join(
        f"c={c:g} {_show(metrics, f'net_benefit_per_{PER_STEPS}_c{c:g}', 2)}"
        for c in FALSE_ALARM_COSTS
    )
    quality = " | ".join(f"{n} {_show(metrics, k)}" for n, k in TEXT_COLUMNS)
    return [f"{head} | {quality}", f"{head} | net benefit per {PER_STEPS} steps: {benefit}"]


def _rows_at_budget(
    counters: ArmTraces,
    flies: Mapping[int, ArmTraces],
    budget: float,
    tasks: Sequence[str],
    draws: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    """Counters, fly seeds and the seed average at one budget, with their difference."""
    counter_point = operating_point(counters, budget, tasks)
    fly_points = {s: operating_point(arm, budget, tasks) for s, arm in flies.items()}
    rows = [
        _arm_rows("counters", "reference", [counter_point], budget, draws),
        _arm_rows("fly", "under_test", list(fly_points.values()), budget, draws),
        *[
            _arm_rows(f"fly seed {s}", "under_test", [p], budget, draws)
            for s, p in fly_points.items()
        ],
    ]
    fly_mean = np.mean([p.counts for p in fly_points.values()], axis=0)
    difference = {
        "budget": budget,
        "what": "fly minus counters",
        "metrics": difference_row(fly_mean, counter_point.counts, draws),
    }
    per_task = {f"counters|{budget}": _per_task_lines(tasks, counter_point.counts)}
    for s, point in fly_points.items():
        per_task[f"fly seed {s}|{budget}"] = _per_task_lines(tasks, point.counts)
    return rows, difference, per_task


def report(
    counters: ArmTraces, flies: Mapping[int, ArmTraces], *, seed: int, n_boot: int = N_BOOT
) -> dict[str, Any]:
    """Rows, fly-minus-counters differences, a short-string table and per-task counts.

    The fly row averages the per-task counts of the wiring seeds, each with its
    own TRAIN threshold, as the G6 rule does. Raises with no fly runs.
    """
    if not flies:
        raise ValueError("no fly runs: the counters row is only half a comparison")
    tasks = sorted({t.task_id for t in counters.test})
    draws = bootstrap_draws(len(tasks), seed=seed, n_boot=n_boot)
    floor_counts = counts_by_task(counters.test, -np.inf, tasks)
    rows = [_row(FLOOR_ARM, "floor", None, budget_row(floor_counts, draws))]
    differences, per_task = [], {}
    for budget in BUDGETS:
        budget_rows, difference, counts = _rows_at_budget(counters, flies, budget, tasks, draws)
        rows += budget_rows
        differences.append(difference)
        per_task.update(counts)
    return {
        "bootstrap": {"draws": n_boot, "seed": seed, "unit": "task", "ci": "95% percentile"},
        "budgets": list(BUDGETS),
        "false_alarm_costs": list(FALSE_ALARM_COSTS),
        "tasks_test": len(tasks),
        "rows": rows,
        "differences": differences,
        "table_rows": [line for row in rows for line in _text_rows(row)],
        "per_task_counts_tp_fp_fn_tn": per_task,
    }
