"""Assemble the scored T46 results (prereg/2026-10-28-note-cost.md). Pure functions of traces.

Input: for each start (repository only, or warm from the pool), learner, seed and held-out
repository, one (TRAIN traces, TEST traces) pair per block (a DenseNet rate or an L2
strength). Every setting is chosen on TRAIN and counted on TEST. Rows are pooled over the
repositories and per repository, with floors, counters beside the fly, and the verdict at the
primary price for the repository-only start.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.eval.note_cost_options import (
    Stack,
    Tiers,
    TierValues,
    budgeted,
    count_stack,
    counts,
    prepare,
    shown,
    tiered_value,
)
from symbiont.eval.note_cost_report import NET, gap, scored
from symbiont.eval.note_cost_scored import (
    Verdict,
    consistent,
    pick_on_train,
    stratified_draws,
    test_counts,
    verdict,
)
from symbiont.eval.note_cost_select import (
    HEADS_UP_COST,
    NOTES_PER_SESSION,
    WARNING_COST,
    Option,
    by_value,
)
from symbiont.eval.note_delivery import Gate, NoteTrace

Traces = tuple[NoteTrace, ...]
Pair = tuple[Traces, Traces]  # (TRAIN, TEST) of one run on one repository
# start -> learner -> seed -> repository -> one pair per block
Runs = Mapping[str, Mapping[str, Mapping[int, Mapping[str, Sequence[Pair]]]]]
ROLES = {
    "counters": "reference",
    "logistic": "reference",
    "dense": "under_test",
    "fly": "under_test",
}
AS_VERDICT = {
    "counters": Verdict.COUNTERS,
    "logistic": Verdict.CLASSIFIER,
    "dense": Verdict.DENSE,
    "fly": Verdict.FLY,
}
PRIMARY = "primary_heads_up_gain_1"
CURVE_COSTS = (0.1, 0.2, 0.3, 0.4, 0.5)
REPO_START = "repo"


def tiered(key: str, heads_gain: float, heads_cost: float) -> Option:
    """Option A at one price: boundaries, 2 notes per session, cooldown, two tiers."""
    value = tiered_value(TierValues(1.0, WARNING_COST, heads_gain, heads_cost))
    rule = budgeted(Gate.BOUNDARY, NOTES_PER_SESSION)
    return Option(key, rule, Tiers.TWO, value, by_value(value))


def registered_options() -> list[Option]:
    """Primary first; the rest are reported and never decide."""
    return [
        tiered(PRIMARY, 1.0, HEADS_UP_COST),
        tiered("sensitivity_heads_up_gain_0.75", 0.75, HEADS_UP_COST),
        tiered("sensitivity_heads_up_gain_0.5", 0.5, HEADS_UP_COST),
        *[tiered(f"curve_heads_up_cost_{c:g}", 1.0, c) for c in CURVE_COSTS],
    ]


@dataclass(frozen=True)
class Layout:
    """Held-out repositories, the pooled task order and the shared bootstrap draws."""

    repos: tuple[str, ...]
    tasks: dict[str, list[str]]  # repository -> its TEST task ids, sorted
    draws: np.ndarray

    def members(self, repo: str) -> np.ndarray:
        """Column positions of one repository's tasks in the pooled order."""
        start = sum(len(self.tasks[r]) for r in self.repos[: self.repos.index(repo)])
        return np.arange(start, start + len(self.tasks[repo]))


def layout_of(runs: Runs, seed: int) -> Layout:
    """Fix the pooled task order from the counters run of the repository-only start."""
    counters = runs[REPO_START]["counters"][0]
    repos = tuple(sorted(counters))
    tasks = {r: sorted({t.task_id for t in counters[r][0][1]}) for r in repos}
    groups = [r for r in repos for _ in tasks[r]]
    return Layout(repos, tasks, stratified_draws(groups, seed=seed))


Choices = dict[str, list[float]]
Row = dict[str, Any]
_STACKS: dict[tuple[int, Any, Tiers], Stack] = {}


def train_stack(train: Traces, option: Option) -> Stack:
    """TRAIN counts of one run, cached: every registered option shares the rule and tiers."""
    key = (id(train), option.rule, option.tiers)
    if key not in _STACKS:
        _STACKS[key] = count_stack(prepare(train, _tasks(train)), option.rule, option.tiers)
    return _STACKS[key]


def learner_counts(
    by_seed: Mapping[int, Mapping[str, Sequence[Pair]]], option: Option, lay: Layout
) -> tuple[np.ndarray, Choices]:
    """Seed-averaged pooled TEST counts, and each seed's TRAIN choice per repository."""
    pooled, chosen = [], {}
    for seed, by_repo in by_seed.items():
        parts = []
        for repo in lay.repos:
            pairs = by_repo[repo]
            stacks = [train_stack(train, option) for train, _ in pairs]
            block, setting = pick_on_train(stacks, option)
            test_arm = prepare(pairs[block][1], lay.tasks[repo])
            parts.append(test_counts(test_arm, stacks[block], setting, option))
            chosen[f"seed {seed} {repo}"] = [block, *stacks[block].settings[setting]]
        pooled.append(np.vstack(parts))
    return np.mean(pooled, axis=0), chosen


def _tasks(traces: Traces) -> list[str]:
    return sorted({t.task_id for t in traces})


def floor_counts(runs: Runs, option: Option, lay: Layout) -> dict[str, np.ndarray]:
    """Warn never and a note at every allowed step, on the counters run's TEST labels."""
    arms = [prepare(runs[REPO_START]["counters"][0][r][0][1], lay.tasks[r]) for r in lay.repos]
    loud = [counts(a, shown(a, -np.inf, option.rule), -np.inf) for a in arms]
    return {
        "warn never": np.vstack([a.totals for a in arms]),
        "note at every allowed step": np.vstack(loud),
    }


@dataclass(frozen=True)
class Where:
    """The option and start a row belongs to."""

    option: Option
    start: str


def rows_for(name: str, role: str, held: np.ndarray, where: Where, lay: Layout) -> list[Row]:
    """Pooled and per-repository rows of one learner under one option and start."""
    value = where.option.value
    rows = [_row(name, role, where, "pooled", scored(held, value, lay.draws))]
    values = []
    for repo in lay.repos:
        cols = lay.members(repo)
        one = scored(held[cols], value, lay.draws[:, cols])
        values.append(one[NET]["value"])
        rows.append(_row(name, role, where, repo, one))
    rows[0]["consistent_across_repos"] = consistent(values)
    return rows


def _row(name: str, role: str, where: Where, repo: str, metrics: dict[str, Any]) -> Row:
    low = metrics[NET]["ci95_low"]
    return {
        "arm": name,
        "role": role,
        "split": "test",
        "option": where.option.key,
        "start": where.start,
        "repo": repo,
        "earns_notes": bool(low is not None and low > 0),
        "metrics": metrics,
    }


def option_rows(
    runs: Runs, where: Where, lay: Layout
) -> tuple[list[Row], dict[str, np.ndarray], dict[str, Choices]]:
    """Every row of one option and start, the held counts and the TRAIN choices."""
    held, chosen = {}, {}
    for name in ROLES:
        held[name], chosen[name] = learner_counts(runs[where.start][name], where.option, lay)
    floors = floor_counts(runs, where.option, lay)
    rows = [r for name, c in floors.items() for r in rows_for(name, "floor", c, where, lay)]
    rows += [r for name in ROLES for r in rows_for(name, ROLES[name], held[name], where, lay)]
    return rows, held, chosen


def differences(held: Mapping[str, np.ndarray], where: Where, lay: Layout) -> list[Row]:
    """Paired pooled differences, with the standing each one supports."""
    pairs = [(n, "counters") for n in ("logistic", "dense", "fly")] + [
        ("fly", "dense"),
        ("fly", "logistic"),
    ]
    found = []
    for first, second in pairs:
        interval = gap(held[first], held[second], where.option.value, lay.draws)
        what = f"{first} minus {second}"
        found.append({"what": what, "option": where.option.key, "start": where.start, **interval})
    return found


def scored_report(runs: Runs, *, seed: int) -> dict[str, Any]:
    """All registered rows, differences, TRAIN choices and the verdict."""
    _STACKS.clear()
    lay = layout_of(runs, seed)
    rows: list[Row] = []
    diffs: list[Row] = []
    choices: dict[str, Any] = {}
    decided: dict[str, Any] = {}
    for start in runs:
        options = registered_options() if start == REPO_START else registered_options()[:3]
        for option in options:
            where = Where(option, start)
            option_rows_, held, chosen = option_rows(runs, where, lay)
            rows += option_rows_
            diffs += differences(held, where, lay)
            choices[f"{start} {option.key}"] = chosen
            if start == REPO_START and option.key == PRIMARY:
                decided = primary_verdict(held, option, lay)
    return {
        "repos": list(lay.repos),
        "tasks_test": {r: len(lay.tasks[r]) for r in lay.repos},
        "bootstrap": {"draws": len(lay.draws), "seed": seed, "unit": "task within repository"},
        "rows": rows,
        "differences": diffs,
        "chosen_on_train": choices,
        "verdict": decided,
    }


def primary_verdict(held: Mapping[str, np.ndarray], option: Option, lay: Layout) -> dict[str, Any]:
    """The registered rule on the pooled primary rows of the repository-only start."""
    benefit = {AS_VERDICT[n]: scored(held[n], option.value, lay.draws)[NET] for n in ROLES}
    versus = {
        AS_VERDICT[n]: gap(held[n], held["counters"], option.value, lay.draws)
        for n in ROLES
        if n != "counters"
    }
    return {
        "live_warner": verdict(benefit, versus),
        "option": option.key,
        "net_value_per_100_steps": {v.value: b for v, b in benefit.items()},
        "versus_counters": {v.value: g for v, g in versus.items()},
        "rule": (
            "best earner by point estimate; it must clear counters on the paired lower bound, "
            "else counters if they earn, else none"
        ),
    }
