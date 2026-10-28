"""Score the note-cost options with task-grouped cross-validation inside TRAIN (T46, exploratory).

Each TRAIN task is counted once, by settings picked on the other four folds
(`note_cost_select`); the T36 test split is not an input. Intervals resample tasks (the same
draws for every row, so differences are paired). The counters row sits beside the fly row in
every option, under warn-never and note-at-every-allowed-step floors. Pure functions of traces.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.eval.net_benefit import interval
from symbiont.eval.note_cost_options import (
    EVERY_STEP,
    FP_HEADS,
    FP_WARN,
    NEVER,
    SESSIONS,
    SPELLS,
    SPELLS_HIT,
    STEPS,
    TP_HEADS,
    TP_WARN,
    Prepared,
    Stack,
    Tiers,
    Value,
    count_stack,
    counts,
    per_step_value,
    prepare,
    shown,
)
from symbiont.eval.note_cost_select import (
    FOLDS,
    PRIMARY,
    Option,
    by_value,
    catalog,
    cross_validate,
    cross_validate_per_fold,
    task_folds,
)
from symbiont.eval.note_delivery import NoteTrace
from symbiont.eval.warning_budget_metrics import N_BOOT, bootstrap_draws

Traces = tuple[NoteTrace, ...]
PER_STEPS = 100
CURVE_COSTS = tuple(round(0.1 * i, 1) for i in range(1, 11))  # option D
NESTED = "logistic"  # batch classifier, its runs keyed by outer fold
ROLES = {"counters": "reference", "fly": "under_test", "dense": "under_test", NESTED: "reference"}
NET = "net_value_per_100_steps"


@dataclass(frozen=True)
class Arms:
    """TRAIN traces: counters, the fly per seed, DenseNet per seed and rate, the classifier."""

    counters: Traces
    fly: Mapping[int, Traces]
    dense: Mapping[int, Mapping[float, Traces]]
    # Batch logistic regression: outer fold -> L2 strength -> out-of-sample traces.
    logistic: Mapping[int, Mapping[float, Traces]] | None = None


Runs = dict[str, dict[int, list[Prepared]]]  # learner -> seed -> one arm per DenseNet rate


def runs_of(arms: Arms, tasks: Sequence[str]) -> Runs:
    """Every learner's arms as arrays, rows in the shared task order."""
    if not arms.fly or not arms.dense:
        raise ValueError("no fly or DenseNet runs: the counters row is only half a comparison")
    runs: Runs = {
        "counters": {0: [prepare(arms.counters, tasks)]},
        "fly": {s: [prepare(t, tasks)] for s, t in arms.fly.items()},
        "dense": {
            s: [prepare(t, tasks) for t in rates.values()] for s, rates in arms.dense.items()
        },
    }
    if arms.logistic is not None:
        runs[NESTED] = {
            f: [prepare(t, tasks) for t in by_l2.values()] for f, by_l2 in arms.logistic.items()
        }
    return runs


class Stacks:
    """Count stacks per (learner, seed), computed once per delivery rule and tier count."""

    def __init__(self, runs: Runs) -> None:
        """Hold the runs; stacks are made on first use."""
        self._runs = runs
        self._made: dict[tuple[Any, Tiers, str], dict[int, list[Stack]]] = {}

    def of(self, learner: str, option: Option) -> dict[int, list[Stack]]:
        """Stacks of every seed of `learner` under the option's rule and tiers."""
        key = (option.rule, option.tiers, learner)
        if key not in self._made:
            self._made[key] = {
                seed: [count_stack(arm, option.rule, option.tiers) for arm in arms]
                for seed, arms in self._runs[learner].items()
            }
        return self._made[key]

    def learners(self) -> list[str]:
        """The learners present, in table order."""
        return [name for name in ROLES if name in self._runs]

    def counters_arm(self) -> Prepared:
        """The counters run, whose labels and boundaries the floors are counted on."""
        return self._runs["counters"][0][0]


def _setting_label(stack: Stack, index: int, rate: int) -> str:
    low, high = stack.settings[index]
    if low == NEVER:
        return f"run {rate} silent"
    warn = "none" if high == NEVER else f"{high:.6g}"
    return f"run {rate} note>={low:.6g} warn>={warn}"


Picked = dict[str, list[str]]


def held_out(
    stacks: dict[int, list[Stack]], folds: np.ndarray, option: Option
) -> tuple[np.ndarray, Picked]:
    """Seed-averaged held-out counts, and what each seed picked in each fold."""
    held, picked = [], {}
    for seed, blocks in stacks.items():
        counts_, chosen = cross_validate([b.counts for b in blocks], folds, option.choose)
        held.append(counts_)
        picked[f"seed {seed}"] = [_setting_label(blocks[b], i, b) for b, i in chosen]
    return np.mean(held, axis=0), picked


def held_out_per_fold(
    stacks: dict[int, list[Stack]], folds: np.ndarray, option: Option
) -> tuple[np.ndarray, Picked]:
    """Held-out counts of the batch classifier: outer fold f is counted with fold f's stacks."""
    counts_, chosen = cross_validate_per_fold(
        {fold: [b.counts for b in blocks] for fold, blocks in stacks.items()}, folds, option.choose
    )
    labels = [_setting_label(stacks[fold][b], i, b) for fold, (b, i) in enumerate(chosen)]
    return counts_, {"outer folds": labels}


def held_for(
    name: str, stacks: Stacks, folds: np.ndarray, option: Option
) -> tuple[np.ndarray, Picked]:
    """Held-out counts of one learner under one option."""
    rule = held_out_per_fold if name == NESTED else held_out
    return rule(stacks.of(name, option), folds, option)


def metrics(totals: np.ndarray, value: Value) -> dict[str, np.ndarray]:
    """Net value per 100 steps and the secondary rates, for each row of summed counts."""
    totals = np.atleast_2d(totals)
    true = totals[:, TP_WARN] + totals[:, TP_HEADS]
    notes = true + totals[:, FP_WARN] + totals[:, FP_HEADS]
    heads = totals[:, TP_HEADS] + totals[:, FP_HEADS]
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            NET: PER_STEPS * value(totals) / totals[:, STEPS],
            "precision": np.where(notes > 0, true / notes, np.nan),
            "notes_per_100_steps": PER_STEPS * notes / totals[:, STEPS],
            "notes_per_session": notes / totals[:, SESSIONS],
            "false_notes_per_session": (notes - true) / totals[:, SESSIONS],
            "heads_up_share": np.where(notes > 0, heads / notes, np.nan),
            "spells_hit_share": totals[:, SPELLS_HIT] / totals[:, SPELLS],
        }


def scored(counts_: np.ndarray, value: Value, draws: np.ndarray) -> dict[str, Any]:
    """Each metric with its task-bootstrap 95% interval."""
    point, sampled = metrics(counts_.sum(axis=0), value), metrics(draws @ counts_, value)
    return {name: interval(float(point[name][0]), sampled[name]) for name in point}


def gap(first: np.ndarray, second: np.ndarray, value: Value, draws: np.ndarray) -> dict[str, Any]:
    """Net value per 100 steps of `first` minus `second`, on the same draws."""
    point = metrics(first.sum(axis=0), value)[NET][0] - metrics(second.sum(axis=0), value)[NET][0]
    sampled = metrics(draws @ first, value)[NET] - metrics(draws @ second, value)[NET]
    return interval(float(point), sampled)


def floors(counters: Prepared, option: Option) -> dict[str, np.ndarray]:
    """Warn never, and a note at every step the rule allows (all at the warning tier)."""
    loudest = shown(counters, -np.inf, option.rule)
    return {
        "warn never": counters.totals.copy(),
        "note at every allowed step": counts(counters, loudest, -np.inf),
    }


def _row(arm: str, role: str, option: Option, scores: dict[str, Any]) -> dict[str, Any]:
    low = scores[NET]["ci95_low"]
    return {
        "arm": arm,
        "role": role,
        "split": "train-cv",
        "option": option.key,
        "earns_notes": bool(low is not None and low > 0),
        "metrics": scores,
    }


def option_block(
    option: Option, stacks: Stacks, folds: np.ndarray, draws: np.ndarray
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Picked]]:
    """Rows, paired differences and fold choices of one option."""
    counters = stacks.counters_arm()
    held = {name: held_for(name, stacks, folds, option) for name in stacks.learners()}
    rows = [
        _row(name, "floor", option, scored(c, option.value, draws))
        for name, c in floors(counters, option).items()
    ]
    rows += [_row(n, ROLES[n], option, scored(h[0], option.value, draws)) for n, h in held.items()]
    pairs = [("fly", "counters"), ("dense", "counters"), ("fly", "dense")]
    if NESTED in held:
        pairs += [(NESTED, "counters"), ("fly", NESTED)]
    gaps = [
        {
            "what": f"{first} minus {second}",
            "option": option.key,
            **gap(held[first][0], held[second][0], option.value, draws),
        }
        for first, second in pairs
    ]
    return rows, gaps, {name: h[1] for name, h in held.items()}


def decision_curve(stacks: Stacks, folds: np.ndarray, draws: np.ndarray) -> dict[str, Any]:
    """Option D offline: the per-step rule re-picked and re-scored at each cost c.

    The online learners only; the classifier row is shown under A, B and C.
    """
    lines = []
    for name in ("counters", "fly", "dense"):
        role = ROLES[name]
        by_cost = []
        for cost in CURVE_COSTS:
            value = per_step_value(cost)
            option = Option(f"d_cost_{cost:g}", EVERY_STEP, Tiers.ONE, value, by_value(value))
            held, _ = held_out(stacks.of(name, option), folds, option)
            by_cost.append({"cost": cost, **scored(held, value, draws)[NET]})
        useful = [p["cost"] for p in by_cost if p["ci95_low"] is not None and p["ci95_low"] > 0]
        lines.append({"arm": name, "role": role, "by_cost": by_cost, "useful_costs": useful})
    return {"costs": list(CURVE_COSTS), "metric": NET, "rows": lines}


def _table_line(row: Mapping[str, Any]) -> str:
    net, prec = row["metrics"][NET], row["metrics"]["precision"]["value"]
    shown_prec = "n/a" if prec is None else f"{prec:.2f}"
    return (
        f"{row['option']} | {row['arm']} | {net['value']:.2f} "
        f"[{net['ci95_low']:.2f}, {net['ci95_high']:.2f}] | prec {shown_prec}"
    )


def report(arms: Arms, *, seed: int, n_boot: int = N_BOOT) -> dict[str, Any]:
    """Every option's rows, differences and fold choices, plus the decision curve."""
    tasks = sorted({t.task_id for t in arms.counters})
    stacks = Stacks(runs_of(arms, tasks))
    folds, draws = (
        task_folds(len(tasks), seed),
        bootstrap_draws(len(tasks), seed=seed, n_boot=n_boot),
    )
    rows, gaps, chosen = [], [], {}
    for option in catalog():
        option_rows, option_gaps, chosen[option.key] = option_block(option, stacks, folds, draws)
        rows += option_rows
        gaps += option_gaps
    return {
        "primary_option": PRIMARY,
        "folds": FOLDS,
        "fold_seed": seed,
        "tasks": len(tasks),
        "bootstrap": {"draws": n_boot, "seed": seed, "unit": "task", "ci": "95% percentile"},
        "rows": rows,
        "differences": gaps,
        "chosen_in_folds": chosen,
        "decision_curve": decision_curve(stacks, folds, draws),
        "table_rows": [_table_line(r) for r in rows if r["role"] != "floor"],
    }
