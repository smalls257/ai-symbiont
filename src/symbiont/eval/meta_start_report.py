"""Rows of the meta-start comparison (T39): option A value per window, repositories as groups.

Every window carries the warn-never floor, counters, the pool classifier and the same classifier
with the online calibrator beside the four filler rows. Thresholds are picked by cross-validation
grouped by repository; intervals resample repositories with the same draws, so differences are
paired. Pure functions of traces.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from symbiont.eval.meta_start import EARLY_SESSIONS
from symbiont.eval.note_cost_options import count_stack, prepare
from symbiont.eval.note_cost_report import NET, floors, gap, held_out, scored
from symbiont.eval.note_cost_select import PRIMARY, Option, catalog, task_folds
from symbiont.eval.note_delivery import NoteTrace
from symbiont.eval.warning_budget_metrics import N_BOOT, bootstrap_draws

Traces = tuple[NoteTrace, ...]
COUNTERS = "counters"
CLASSIFIER = "logistic"
ADAPTING_CLASSIFIER = "logistic + online calibrator"
ROLES = {
    COUNTERS: "reference",
    CLASSIFIER: "reference",
    ADAPTING_CLASSIFIER: "reference",
    "fly cold start": "under_test",
    "fly meta start": "under_test",
    "dense cold start": "under_test",
    "dense meta start": "under_test",
}
# Primary: option A with a heads-up worth a right warning (c = 0.25). Sensitivity: worth 0.75.
OPTIONS = {"a_heads_up_gain_1": "primary", PRIMARY: "sensitivity heads-up gain 0.75"}
WINDOWS = ("first 10 sessions", "after 10 sessions")
PAIRS = (
    ("fly meta start", "fly cold start"),
    ("dense meta start", "dense cold start"),
    ("fly meta start", ADAPTING_CLASSIFIER),
    ("dense meta start", ADAPTING_CLASSIFIER),
    ("fly meta start", COUNTERS),
    ("dense meta start", COUNTERS),
    (ADAPTING_CLASSIFIER, CLASSIFIER),
)
Arms = Mapping[str, Mapping[int, Traces]]  # row -> seed -> traces in replay order


def window_of(traces: Traces, window: str) -> Traces:
    """The sessions of each repository inside `window`, in replay order."""
    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r}")
    seen: dict[str, int] = {}
    kept = []
    for trace in traces:
        position = seen.get(trace.task_id, 0)
        seen[trace.task_id] = position + 1
        if (position < EARLY_SESSIONS) == (window == WINDOWS[0]):
            kept.append(trace)
    return tuple(kept)


def _held(
    traces_by_seed: Mapping[int, Traces], repos: list[str], folds: np.ndarray, option: Option
) -> np.ndarray:
    """Held-out counts per scoring repository for one option, from the seeds' traces."""
    stacks = {
        seed: [count_stack(prepare(t, repos), option.rule, option.tiers)]
        for seed, t in traces_by_seed.items()
    }
    return held_out(stacks, folds, option)[0]


def _row(
    name: str, role: str, window: str, option: Option, scores: dict[str, Any]
) -> dict[str, Any]:
    """One results row for an arm in a window."""
    low = scores[NET]["ci95_low"]
    return {
        "arm": name,
        "role": role,
        "window": window,
        "option": option.key,
        "earns_notes": bool(low is not None and low > 0),
        "metrics": scores,
    }


Block = tuple[list[dict[str, Any]], list[dict[str, Any]]]


def window_block(arms: Arms, window: str, option: Option, seed: int, n_boot: int) -> Block:
    """Rows and paired differences of one window under one option."""
    cut = {
        name: {s: window_of(t, window) for s, t in by_seed.items()}
        for name, by_seed in arms.items()
    }
    repos = sorted({t.task_id for t in cut[COUNTERS][0]})
    folds, draws = (
        task_folds(len(repos), seed),
        bootstrap_draws(len(repos), seed=seed, n_boot=n_boot),
    )
    counters = prepare(cut[COUNTERS][0], repos)
    held = {name: _held(cut[name], repos, folds, option) for name in ROLES}
    rows = [
        _row(name, "floor", window, option, scored(c, option.value, draws))
        for name, c in floors(counters, option).items()
        if name == "warn never"
    ]
    rows += [
        _row(n, ROLES[n], window, option, scored(h, option.value, draws)) for n, h in held.items()
    ]
    gaps = [
        {"what": f"{a} minus {b}", "window": window, "option": option.key}
        | gap(held[a], held[b], option.value, draws)
        for a, b in PAIRS
    ]
    return rows, gaps


def meta_report(arms: Arms, *, seed: int, n_boot: int = N_BOOT) -> dict[str, Any]:
    """Every row and difference, per window and option. Raises if a row is missing."""
    missing = sorted(set(ROLES) - set(arms))
    if missing:
        raise ValueError(f"missing rows {missing}: a meta start is judged beside every one")
    options = [o for o in catalog() if o.key in OPTIONS]
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for option in options:
        for window in WINDOWS:
            block_rows, block_gaps = window_block(arms, window, option, seed, n_boot)
            rows += block_rows
            gaps += block_gaps
    return {
        "options": dict(OPTIONS),
        "windows": list(WINDOWS),
        "early_sessions": EARLY_SESSIONS,
        "repos": len({t.task_id for t in arms[COUNTERS][0]}),
        "bootstrap": {"draws": n_boot, "seed": seed, "unit": "repository", "ci": "95% percentile"},
        "rows": rows,
        "differences": gaps,
        "table_rows": [table_line(r) for r in rows],
    }


def table_line(row: Mapping[str, Any]) -> str:
    """One row as `option | window | arm | value [low, high]`."""
    net = row["metrics"][NET]
    low, high = (np.nan if v is None else v for v in (net["ci95_low"], net["ci95_high"]))
    return (
        f"{row['option']} | {row['window']} | {row['arm']} ({row['role']}) | "
        f"{net['value']:.3f} [{low:.3f}, {high:.3f}]"
    )


def note_traces(
    repo: str,
    followed: Sequence[np.ndarray],
    risks: Sequence[np.ndarray],
    boundary: Sequence[np.ndarray],
) -> Traces:
    """One repository's sessions as note traces; the repository is the group."""
    return tuple(
        NoteTrace(repo, tuple(map(bool, y)), tuple(map(float, r)), tuple(map(bool, b)))
        for y, r, b in zip(followed, risks, boundary, strict=True)
    )
