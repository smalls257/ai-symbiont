"""The scored T39 comparison (prereg/2026-10-28-meta-start.md), pure functions of traces.

Violation prevented: **Paper Tiger**. A meta start judged only against its own cold start
could lose to plain counters or to one classifier and still be reported as a win, and a
"worse" could be softened into "no gain". So every row is scored beside the floors, counters
and both classifiers; every setting is chosen on the validation repositories and then fixed
(nothing is fit on a scoring repository); each comparison ends in one word, better, tie or
worse, read off its paired interval; and the best-row rule names the plainest row on ties.

Input, per window: row -> wiring seed -> (validation traces, scoring traces). Intervals
resample tasks within each scoring repository with the same draws for every row.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from symbiont.eval.note_cost_options import count_stack, counts, prepare, shown
from symbiont.eval.note_cost_report import NET, gap, scored
from symbiont.eval.note_cost_scored import consistent, pick_on_train, stratified_draws, test_counts
from symbiont.eval.note_cost_scored_report import PRIMARY, registered_options
from symbiont.eval.note_cost_select import Option
from symbiont.eval.note_delivery import NoteTrace

Traces = tuple[NoteTrace, ...]
Pair = tuple[Traces, Traces]  # (validation, scoring) of one run
Rows = Mapping[str, Mapping[int, Pair]]
COUNTERS, FIXED, ADAPTING = "counters", "logistic", "logistic + online calibrator"
# Tie order, plainest first (prereg rule 8).
ROLES = {
    COUNTERS: "reference",
    FIXED: "reference (a standard supervised baseline)",
    ADAPTING: "reference (the fixed classifier plus the fillers' online calibrator)",
    "dense cold start": "under_test",
    "dense meta start": "under_test",
    "fly cold start": "under_test",
    "fly meta start": "under_test",
}
COMPARISONS = {
    "H1 fly": ("fly meta start", "fly cold start"),
    "H1 dense": ("dense meta start", "dense cold start"),
    "H2 fly": ("fly meta start", ADAPTING),
    "H2 dense": ("dense meta start", ADAPTING),
    "H3 fly": ("fly meta start", FIXED),
    "H3 dense": ("dense meta start", FIXED),
    "H4": (ADAPTING, FIXED),
    "fly meta start minus counters": ("fly meta start", COUNTERS),
    "dense meta start minus counters": ("dense meta start", COUNTERS),
}


@dataclass(frozen=True)
class Layout:
    """Scoring tasks in pooled order, their repository, and the shared bootstrap draws."""

    tasks: tuple[str, ...]
    repo_of: Mapping[str, str]
    draws: np.ndarray

    @classmethod
    def of(cls, repo_of: Mapping[str, str], seed: int, n_boot: int) -> "Layout":
        """Tasks sorted by repository then id; draws resample within each repository."""
        tasks = tuple(sorted(repo_of, key=lambda task: (repo_of[task], task)))
        groups = [repo_of[t] for t in tasks]
        return cls(tasks, repo_of, stratified_draws(groups, seed=seed, n_boot=n_boot))

    def members(self, repo: str) -> np.ndarray:
        """Positions of one repository's tasks."""
        return np.flatnonzero([self.repo_of[t] == repo for t in self.tasks])

    def repos(self) -> list[str]:
        """The scoring repositories, sorted."""
        return sorted(set(self.repo_of.values()))


def verdict_word(interval: Mapping[str, Any]) -> str:
    """Better if the paired interval is above 0, worse if below, else tie."""
    if interval["ci95_low"] is not None and interval["ci95_low"] > 0:
        return "better"
    if interval["ci95_high"] is not None and interval["ci95_high"] < 0:
        return "worse"
    return "tie"


def row_counts(
    by_seed: Mapping[int, Pair], option: Option, lay: Layout
) -> tuple[np.ndarray, dict[str, list[float]]]:
    """Seed-averaged scoring counts at the setting each seed's validation run chose."""
    held, chosen = [], {}
    for seed, (validation, scoring) in by_seed.items():
        tasks = sorted({t.task_id for t in validation})
        stack = count_stack(prepare(validation, tasks), option.rule, option.tiers)
        _, setting = pick_on_train([stack], option)
        held.append(test_counts(prepare(scoring, lay.tasks), stack, setting, option))
        chosen[f"seed {seed}"] = [float(v) for v in stack.settings[setting]]
    return np.mean(held, axis=0), chosen


def floor_counts(rows: Rows, option: Option, lay: Layout) -> dict[str, np.ndarray]:
    """Warn never and a note at every allowed step, on the counters run's scoring labels."""
    arm = prepare(rows[COUNTERS][0][1], lay.tasks)
    return {
        "warn never": arm.totals.copy(),
        "note at every allowed step": counts(arm, shown(arm, -np.inf, option.rule), -np.inf),
    }


def rows_of(
    name: str, role: str, held: np.ndarray, option: Option, lay: Layout
) -> list[dict[str, Any]]:
    """The pooled row and one row per scoring repository."""
    found = [{"arm": name, "role": role, "repo": "pooled", **_scores(held, option, lay.draws)}]
    for repo in lay.repos():
        cols = lay.members(repo)
        found.append(
            {
                "arm": name,
                "role": role,
                "repo": repo,
                **_scores(held[cols], option, lay.draws[:, cols]),
            }
        )
    return found


def _scores(held: np.ndarray, option: Option, draws: np.ndarray) -> dict[str, Any]:
    return {"metrics": scored(held, option.value, draws)}


def comparisons(
    held: Mapping[str, np.ndarray], option: Option, lay: Layout
) -> list[dict[str, Any]]:
    """Every registered paired difference, its word, and the per-repository sign tag."""
    found = []
    for name, (first, second) in COMPARISONS.items():
        pooled = gap(held[first], held[second], option.value, lay.draws)
        per_repo = [
            gap(held[first][c], held[second][c], option.value, lay.draws[:, c])["value"]
            for c in map(lay.members, lay.repos())
        ]
        found.append(
            {
                "what": name,
                "first": first,
                "second": second,
                **pooled,
                "verdict": verdict_word(pooled),
                "per_repo": dict(zip(lay.repos(), per_repo, strict=True)),
                "consistent_across_repos": consistent(per_repo),
            }
        )
    return found


def best_row(held: Mapping[str, np.ndarray], option: Option, lay: Layout) -> str:
    """T46 rules 1, 4, 5 over every row, plainest first on ties; 'none' if no row earns."""
    value = {row: scored(held[row], option.value, lay.draws)[NET] for row in ROLES}
    earners = [row for row in ROLES if (value[row]["ci95_low"] or 0) > 0]
    if not earners:
        return "none"
    order = list(ROLES)
    best = max(earners, key=lambda row: (round(value[row]["value"], 12), -order.index(row)))
    if best == COUNTERS:
        return best
    versus = gap(held[best], held[COUNTERS], option.value, lay.draws)
    if versus["ci95_low"] is not None and versus["ci95_low"] > 0:
        return best
    return COUNTERS if COUNTERS in earners else "none"


def window_block(rows: Rows, option: Option, lay: Layout) -> dict[str, Any]:
    """Rows, comparisons, best row and chosen settings of one window under one option."""
    missing = sorted(set(ROLES) - set(rows))
    if missing:
        raise ValueError(f"missing rows {missing}: every row is scored beside the others")
    picked = {name: row_counts(rows[name], option, lay) for name in ROLES}
    held = {name: counts_ for name, (counts_, _) in picked.items()}
    found = []
    for name, floor in floor_counts(rows, option, lay).items():
        found += rows_of(name, "floor", floor, option, lay)
    for name in ROLES:
        found += rows_of(name, ROLES[name], held[name], option, lay)
    return {
        "rows": found,
        "comparisons": comparisons(held, option, lay),
        "best_row": best_row(held, option, lay),
        "chosen_on_validation": {name: chosen for name, (_, chosen) in picked.items()},
    }


@dataclass(frozen=True)
class Window:
    """One window's rows, and the repository of each resampling unit in its traces.

    The unit is a trace's `task_id`: a task where a window holds many, a session where it
    holds only a few tasks (each repository's first 10 sessions come from one or two).
    """

    rows: Rows
    repo_of: Mapping[str, str]
    unit: str


def meta_scored_report(
    windows: Mapping[str, Window], *, seed: int, n_boot: int = 2000
) -> dict[str, Any]:
    """Every window under every registered price; the primary price comes first."""
    layouts = {name: Layout.of(w.repo_of, seed, n_boot) for name, w in windows.items()}
    blocks = []
    for option in registered_options():
        for name, window in windows.items():
            lay = layouts[name]
            blocks.append(
                {"option": option.key, "window": name, **window_block(window.rows, option, lay)}
            )
    return {
        "primary_option": PRIMARY,
        "windows": {
            name: {
                "unit": w.unit,
                "units": len(layouts[name].tasks),
                "repos": layouts[name].repos(),
            }
            for name, w in windows.items()
        },
        "bootstrap": {"draws": n_boot, "seed": seed, "resampled": "units within each repository"},
        "blocks": blocks,
        "table_rows": table_rows(blocks),
    }


def table_rows(blocks: Sequence[Mapping[str, Any]]) -> list[str]:
    """Pooled primary-price rows and verdict words, one line each."""
    lines = []
    for block in blocks:
        if block["option"] != PRIMARY:
            continue
        for row in block["rows"]:
            if row["repo"] == "pooled":
                net = row["metrics"][NET]
                lines.append(
                    f"{block['window']} | {row['arm']} | {net['value']:.3f} "
                    f"[{net['ci95_low']:.3f}, {net['ci95_high']:.3f}]"
                )
        lines += [
            f"{block['window']} | {c['what']} | {c['verdict']} {c['value']:.3f} "
            f"[{c['ci95_low']:.3f}, {c['ci95_high']:.3f}]"
            for c in block["comparisons"][:7]
        ]
    return lines
