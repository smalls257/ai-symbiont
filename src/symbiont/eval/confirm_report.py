"""The scored T48 confirm run's rules: pool-fixed thresholds, pooled rows, verdict, confirm call.

prereg/2026-10-28-confirm.md fixes every rule here. Unlike T46 nothing is chosen on the scored
repositories: each (row, seed) arrives with its (note, warning) thresholds already fixed on the
pool, and every task of every repository is counted at them. Pooled intervals resample tasks
within each repository with the same draws for every row (T46's `stratified_draws`), so
differences are paired. Pure functions of traces and thresholds.

Violation prevented: **Silent Fallback** at the claim level. A confirm table that could name a
new winner without saying the pool's choice failed would be a second selection dressed as a
confirmation; `confirm_call` states "confirms" or "contradicts" from rules fixed before the run.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

import numpy as np

from symbiont.eval.note_cost_options import NEVER, counts, prepare, shown
from symbiont.eval.note_cost_report import NET, gap, scored
from symbiont.eval.note_cost_scored import consistent, stratified_draws
from symbiont.eval.note_cost_select import Option
from symbiont.eval.note_delivery import NoteTrace

Traces = tuple[NoteTrace, ...]
Thresholds = tuple[float, float]  # (note at or above, warning at or above); NEVER for silence
COUNTERS, CLASSIFIER = "counters", "logistic regression"
DENSE, FLY, FLY_FIXED = "DenseNet combined", "fly as is", "fly combined"
TIE_ORDER = (COUNTERS, CLASSIFIER, DENSE, FLY, FLY_FIXED)  # plainest first (prereg rule 1)
NAMED_DIFFERENCES = (
    (FLY_FIXED, COUNTERS),
    (FLY_FIXED, CLASSIFIER),
    (FLY_FIXED, FLY),
    (FLY_FIXED, DENSE),
)
NONE = "none"


@dataclass(frozen=True)
class Layout:
    """Scored repositories, each one's task ids in pooled order, and the shared draws."""

    repos: tuple[str, ...]
    tasks: Mapping[str, Sequence[str]]
    draws: np.ndarray

    def members(self, repo: str) -> np.ndarray:
        """Column positions of one repository's tasks in the pooled order."""
        start = sum(len(self.tasks[r]) for r in self.repos[: self.repos.index(repo)])
        return np.arange(start, start + len(self.tasks[repo]))


def layout_of(by_repo: Mapping[str, Traces], seed: int, n_boot: int) -> Layout:
    """Pooled task order (repositories sorted, tasks sorted) and draws within repository."""
    repos = tuple(sorted(by_repo))
    tasks = {r: sorted({t.task_id for t in by_repo[r]}) for r in repos}
    groups = [r for r in repos for _ in tasks[r]]
    return Layout(repos, tasks, stratified_draws(groups, seed=seed, n_boot=n_boot))


def fixed_counts(
    traces: Traces, tasks: Sequence[str], at: Thresholds, option: Option
) -> np.ndarray:
    """Per-task counts of one run at thresholds fixed before it was seen."""
    arm = prepare(traces, tasks)
    note, warn = at
    return counts(arm, shown(arm, note, option.rule), warn)


def row_counts(
    by_seed: Mapping[int, Mapping[str, Traces]],
    at: Mapping[int, Thresholds],
    option: Option,
    lay: Layout,
) -> np.ndarray:
    """Seed-averaged pooled per-task counts of one row."""
    per_seed = [
        np.vstack([fixed_counts(by_repo[r], lay.tasks[r], at[seed], option) for r in lay.repos])
        for seed, by_repo in by_seed.items()
    ]
    return np.asarray(np.mean(per_seed, axis=0))


def floor_counts(
    counters: Mapping[str, Traces], option: Option, lay: Layout
) -> dict[str, np.ndarray]:
    """Warn never, and a note at every allowed step (all warnings), on the counters labels."""
    arms = [prepare(counters[r], lay.tasks[r]) for r in lay.repos]
    return {
        "warn never": np.vstack([a.totals for a in arms]),
        "note at every allowed step": np.vstack(
            [counts(a, shown(a, -np.inf, option.rule), -np.inf) for a in arms]
        ),
    }


class Row(TypedDict):
    """One scored row: a learner or floor under one option, pooled or one repository."""

    arm: str
    role: str
    option: str
    repo: str
    metrics: dict[str, Any]  # `note_cost_report.scored`'s metric -> interval mapping
    earns_notes: bool
    consistent_across_repos: NotRequired[bool]


def _row(name: str, role: str, option: Option, repo: str, metrics: dict[str, Any]) -> Row:
    low = metrics[NET]["ci95_low"]
    earns = bool(low is not None and low > 0)
    return Row(
        arm=name, role=role, option=option.key, repo=repo, metrics=metrics, earns_notes=earns
    )


def rows_of(name: str, role: str, held: np.ndarray, option: Option, lay: Layout) -> list[Row]:
    """The pooled row (with its consistency tag) and one row per repository."""
    value = option.value
    pooled = _row(name, role, option, "pooled", scored(held, value, lay.draws))
    per_repo = []
    for repo in lay.repos:
        cols = lay.members(repo)
        per_repo.append(
            _row(name, role, option, repo, scored(held[cols], value, lay.draws[:, cols]))
        )
    pooled["consistent_across_repos"] = consistent([r["metrics"][NET]["value"] for r in per_repo])
    return [pooled, *per_repo]


def standing(interval: Mapping[str, Any]) -> str:
    """`better`, `tie` or `worse` from a paired interval (prereg rule 5)."""
    if interval["ci95_low"] > 0:
        return "better"
    if interval["ci95_high"] < 0:
        return "worse"
    return "tie"


def differences(
    held: Mapping[str, np.ndarray], option: Option, lay: Layout
) -> dict[str, dict[str, Any]]:
    """Every candidate minus counters (rule 4) and the four named differences (rule 5)."""
    pairs = [(name, COUNTERS) for name in TIE_ORDER if name != COUNTERS]
    pairs += [p for p in NAMED_DIFFERENCES if p not in pairs]
    found = {}
    for first, second in pairs:
        interval = gap(held[first], held[second], option.value, lay.draws)
        found[f"{first} minus {second}"] = {**interval, "standing": standing(interval)}
    return found


def verdict(
    benefit: Mapping[str, Mapping[str, Any]], versus_counters: Mapping[str, Mapping[str, Any]]
) -> str:
    """The registered rule: best earner by point estimate, which must clear counters (rules 1-4)."""
    earners = [c for c in TIE_ORDER if benefit[c]["ci95_low"] > 0]
    if not earners:
        return NONE
    best = max(earners, key=lambda who: (round(benefit[who]["value"], 12), -TIE_ORDER.index(who)))
    if best == COUNTERS or versus_counters[best]["ci95_low"] > 0:
        return best
    return COUNTERS if COUNTERS in earners else NONE


def confirm_call(
    live: str, benefit: Mapping[str, Mapping[str, Any]], diffs: Mapping[str, Mapping[str, Any]]
) -> str:
    """`confirms` or `contradicts` the pool's pick, by the prereg's definition."""
    classifier_ok = benefit[CLASSIFIER]["ci95_low"] > 0 and live == CLASSIFIER
    fly_beats_counters = diffs[f"{FLY_FIXED} minus {COUNTERS}"]["ci95_low"] > 0
    fly_not_above_classifier = not diffs[f"{FLY_FIXED} minus {CLASSIFIER}"]["ci95_low"] > 0
    if classifier_ok and fly_beats_counters and fly_not_above_classifier:
        return "confirms"
    return "contradicts"


def thresholds_of(setting: Mapping[str, float | None]) -> Thresholds:
    """(note, warning) from a settings-file entry; None means that tier never speaks."""
    note, warn = setting["note_at_or_above"], setting["warning_at_or_above"]
    return (NEVER if note is None else float(note), NEVER if warn is None else float(warn))
