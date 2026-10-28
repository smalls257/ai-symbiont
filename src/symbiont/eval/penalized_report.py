"""Assemble the penalized-selection results from risk traces (T36 prereg).

Every threshold and DenseNet learning rate comes from TRAIN traces only; test
traces are only counted against the choice. Pure functions of traces: no file,
clock or network. Output is counts, ids and labels.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.eval.net_benefit import (
    COSTS,
    NEVER,
    PRIMARY_COST,
    TrainChoice,
    Warner,
    best_threshold,
    live_warner,
    net_benefit_gap,
    net_benefit_interval,
    standing,
)
from symbiont.eval.warning_budget_metrics import (
    N_BOOT,
    RiskTrace,
    bootstrap_draws,
    budget_row,
    counts_by_task,
    flat_risks,
)
from symbiont.eval.warning_budget_report import ArmTraces

PER_STEPS = 100
SECONDARY = ("precision", "recall", "flag_rate")
Rows = list[dict[str, Any]]


@dataclass(frozen=True)
class Picked:
    """One learner run with its TRAIN-chosen setting and its TEST counts per task."""

    choice: TrainChoice
    counts: np.ndarray
    learning_rate: float | None = None


def _labels(traces: Sequence[RiskTrace]) -> tuple[list[float | None], list[bool]]:
    """Flat risk scores and followed-by-pain-point labels across traces."""
    return flat_risks(traces), [flag for trace in traces for flag in trace.followed]


def train_choice(arm: ArmTraces, cost: float) -> TrainChoice:
    """The best threshold on this run's TRAIN steps."""
    return best_threshold(*_labels(arm.train), cost)


def pick(arm: ArmTraces, cost: float, tasks: Sequence[str]) -> Picked:
    """Choose on TRAIN, then count TEST at the frozen threshold."""
    choice = train_choice(arm, cost)
    return Picked(choice, counts_by_task(arm.test, choice.threshold, tasks))


def pick_dense(by_rate: Mapping[float, ArmTraces], cost: float, tasks: Sequence[str]) -> Picked:
    """The learning rate with the best TRAIN net benefit (ties to the first listed), then pick."""
    rates = list(by_rate)
    scored = {rate: train_choice(by_rate[rate], cost).net_benefit for rate in rates}
    best = rates[0]
    for rate in rates:
        if scored[rate] > scored[best]:
            best = rate
    chosen = pick(by_rate[best], cost, tasks)
    return Picked(chosen.choice, chosen.counts, learning_rate=best)


def _mean_counts(picks: Sequence[Picked]) -> np.ndarray:
    """Per-task counts averaged over a learner's runs."""
    return np.mean([p.counts for p in picks], axis=0)


def _row(
    arm: str, role: str, cost: float | None, counts: np.ndarray, draws: np.ndarray
) -> dict[str, Any]:
    """One results row; net benefit is only reported when a cost is given."""
    secondary = budget_row(counts, draws)
    metrics: dict[str, Any] = {name: secondary[name] for name in SECONDARY}
    if cost is not None:
        per_step = net_benefit_interval(counts, draws, cost)
        metrics["net_benefit_per_step"] = per_step
        metrics["net_benefit_per_100_steps"] = {
            k: v * PER_STEPS if isinstance(v, float) else v for k, v in per_step.items()
        }
    return {"arm": arm, "role": role, "split": "test", "cost": cost, "metrics": metrics}


def _setting(picked: Picked) -> dict[str, Any]:
    """The train-chosen threshold and learning rate; `warns_never` marks the never-warn choice."""
    never = picked.choice.threshold == NEVER
    return {
        "threshold": None if never else picked.choice.threshold,
        "warns_never": never,
        "train_net_benefit_per_step": picked.choice.net_benefit,
        "learning_rate": picked.learning_rate,
    }


@dataclass(frozen=True)
class Picks:
    """Every learner's TRAIN-chosen runs at one cost."""

    counters: Picked
    fly: dict[int, Picked]
    dense: dict[int, Picked]

    def arms(self) -> dict[str, np.ndarray]:
        """Test counts per task for each reported learner row, the seed averages first."""
        return {
            "counters": self.counters.counts,
            "fly": _mean_counts(list(self.fly.values())),
            "dense": _mean_counts(list(self.dense.values())),
            **{f"fly seed {s}": p.counts for s, p in self.fly.items()},
            **{f"dense seed {s}": p.counts for s, p in self.dense.items()},
        }

    def settings(self) -> dict[str, Any]:
        """What was chosen on TRAIN, for the results file."""
        return {
            "counters": _setting(self.counters),
            **{f"fly seed {s}": _setting(p) for s, p in self.fly.items()},
            **{f"dense seed {s}": _setting(p) for s, p in self.dense.items()},
        }


def picks_at(
    counters: ArmTraces,
    flies: Mapping[int, ArmTraces],
    dense: Mapping[int, Mapping[float, ArmTraces]],
    cost: float,
    tasks: Sequence[str],
) -> Picks:
    """All learners' TRAIN choices at `cost`, applied to TEST."""
    return Picks(
        pick(counters, cost, tasks),
        {s: pick(arm, cost, tasks) for s, arm in flies.items()},
        {s: pick_dense(by_rate, cost, tasks) for s, by_rate in dense.items()},
    )


ROLES = {"counters": "reference", "fly": "under_test", "dense": "under_test"}


def _role(arm: str) -> str:
    """The row's label (reference or under_test) from its arm name."""
    return ROLES[arm.split(" ")[0]]


def rows_at(picks: Picks, floor_counts: Mapping[str, np.ndarray], cost: float, draws: Any) -> Rows:
    """Floors and learners at one cost, each with its interval."""
    floors = [_row(name, "floor", cost, counts, draws) for name, counts in floor_counts.items()]
    arms = [_row(n, _role(n), cost, counts, draws) for n, counts in picks.arms().items()]
    return floors + arms


def gaps_at(picks: Picks, cost: float, draws: np.ndarray) -> list[dict[str, Any]]:
    """Paired differences between the seed-averaged rows, with the standing of each."""
    arms = picks.arms()
    pairs = (("fly", "counters"), ("dense", "counters"), ("fly", "dense"))
    gaps = []
    for first, second in pairs:
        gap = net_benefit_gap(arms[first], arms[second], draws, cost)
        gaps.append(
            {"what": f"{first} minus {second}", "cost": cost, **gap, "standing": standing(gap)}
        )
    return gaps


def verdict_at_primary(picks: Picks, draws: np.ndarray) -> dict[str, Any]:
    """Apply the registered decision rule at c = 0.5."""
    arms = picks.arms()
    benefit = {
        Warner(name): net_benefit_interval(arms[name], draws, PRIMARY_COST)
        for name in ("counters", "dense", "fly")
    }
    versus = {
        Warner(name): net_benefit_gap(arms[name], arms["counters"], draws, PRIMARY_COST)
        for name in ("dense", "fly")
    }
    return {
        "live_warner": live_warner(benefit, versus),
        "cost": PRIMARY_COST,
        "net_benefit_per_step": {w.value: b for w, b in benefit.items()},
        "rule": "best candidate whose ci95_low > 0; counters if it does not clearly beat them",
    }


def _per_task_lines(tasks: Sequence[str], counts: np.ndarray) -> list[str]:
    """One `task,count,...` line per task."""
    return [
        f"{t},{','.join(str(int(c)) for c in row)}" for t, row in zip(tasks, counts, strict=True)
    ]


def _table_line(row: Mapping[str, Any]) -> str:
    """A markdown-table cell line for one row; an undefined net benefit says so."""
    metrics = row["metrics"]["net_benefit_per_100_steps"]
    if metrics["value"] is None:
        return f"{row['arm']} | c={row['cost']:g} | undefined"
    low, high = metrics["ci95_low"], metrics["ci95_high"]
    return (
        f"{row['arm']} | c={row['cost']:g} | NB/100 {metrics['value']:.2f} [{low:.2f}, {high:.2f}]"
    )


def report(
    counters: ArmTraces,
    flies: Mapping[int, ArmTraces],
    dense: Mapping[int, Mapping[float, ArmTraces]],
    *,
    seed: int,
    n_boot: int = N_BOOT,
) -> dict[str, Any]:
    """Rows at every cost, gaps, chosen settings, the verdict and per-task counts."""
    if not flies or not dense:
        raise ValueError("no fly or DenseNet runs: the counters row is only half a comparison")
    tasks = sorted({t.task_id for t in counters.test})
    draws = bootstrap_draws(len(tasks), seed=seed, n_boot=n_boot)
    floors = {
        "warn never": counts_by_task(counters.test, NEVER, tasks),
        "warn on every step": counts_by_task(counters.test, -np.inf, tasks),
    }
    by_cost = {cost: picks_at(counters, flies, dense, cost, tasks) for cost in COSTS}
    rows = [r for cost, p in by_cost.items() for r in rows_at(p, floors, cost, draws)]
    gaps = [g for cost, p in by_cost.items() for g in gaps_at(p, cost, draws)]
    primary = by_cost[PRIMARY_COST]
    return {
        "bootstrap": {"draws": n_boot, "seed": seed, "unit": "task", "ci": "95% percentile"},
        "costs": list(COSTS),
        "primary_cost": PRIMARY_COST,
        "tasks_test": len(tasks),
        "rows": rows,
        "differences": gaps,
        "chosen_on_train": {f"{cost:g}": p.settings() for cost, p in by_cost.items()},
        "verdict": verdict_at_primary(primary, draws),
        "table_rows": [_table_line(r) for r in rows],
        "per_task_counts_tp_fp_fn_tn_at_primary_cost": {
            name: _per_task_lines(tasks, counts) for name, counts in primary.arms().items()
        },
    }
