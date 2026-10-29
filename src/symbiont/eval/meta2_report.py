"""META2 scoring: option A value per window (a repository's first 10 tasks, and the rest). Pure.

Each row arrives as per-task risks per wiring seed and repository. Its (note, warning) pair is
chosen by the T46 rule on the validation repositories' traces, every task, and then fixed; the
same thresholds price both windows. Pooled intervals resample tasks within each repository with
the same draws for every row, so differences are paired. Rows are seed means of per-task counts.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from symbiont.eval.confirm_report import Thresholds, layout_of, row_counts, standing
from symbiont.eval.meta2_replay import RepoTasks
from symbiont.eval.meta2_tasks import EARLY_TASKS, SEED
from symbiont.eval.note_cost_options import count_stack, prepare
from symbiont.eval.note_cost_report import NET, gap, scored
from symbiont.eval.note_cost_scored_report import PRIMARY, registered_options
from symbiont.eval.note_cost_select import Option
from symbiont.eval.note_delivery import NoteTrace

Traces = tuple[NoteTrace, ...]
BySeed = Mapping[int, Mapping[str, Traces]]  # wiring seed -> repository -> one trace per task
N_BOOT = 2000


class Window(StrEnum):
    """Which of a repository's tasks a number covers."""

    EARLY = "first 10 tasks"
    LATE = "after 10 tasks"
    ALL = "all tasks"


def primary_option() -> Option:
    """Option A at the primary price (heads-up +1/-0.25, warning +1/-0.5)."""
    return next(o for o in registered_options() if o.key == PRIMARY)


def task_traces(repo: RepoTasks, risks: Sequence[np.ndarray]) -> Traces:
    """One trace per task, keyed by the task id, so the bootstrap resamples tasks."""
    if len(risks) != len(repo.task_ids):
        raise ValueError(f"{repo.repo}: risks for {len(risks)} of {len(repo.task_ids)} tasks")
    return tuple(
        NoteTrace(task, tuple(map(bool, y)), tuple(map(float, r)), tuple(map(bool, b)))
        for task, y, r, b in zip(repo.task_ids, repo.followed, risks, repo.boundary, strict=True)
    )


def in_window(traces: Traces, window: Window) -> Traces:
    """The traces of one window; traces are in issue order."""
    if window is Window.EARLY:
        return traces[:EARLY_TASKS]
    if window is Window.LATE:
        return traces[EARLY_TASKS:]
    return traces


def choose_thresholds(by_repo: Mapping[str, Traces], option: Option) -> Thresholds:
    """The T46 rule on every task of these repositories: best value per step, else silence."""
    traces = tuple(t for repo in sorted(by_repo) for t in by_repo[repo])
    arm = prepare(traces, sorted({t.task_id for t in traces}))
    stack = count_stack(arm, option.rule, option.tiers)
    index, _ = option.choose(stack.counts)
    note, warn = stack.settings[index]
    return note, warn


@dataclass(frozen=True)
class Scored:
    """One row's pooled per-task counts in one window, and the layout they were counted on."""

    counts: np.ndarray
    layout: Any


def window_counts(
    by_seed: BySeed, at: Mapping[int, Thresholds], window: Window, option: Option
) -> Scored:
    """Seed-mean per-task counts of one row in one window, at fixed thresholds."""
    windowed = {s: {r: in_window(t, window) for r, t in rs.items()} for s, rs in by_seed.items()}
    first = next(iter(windowed.values()))
    lay = layout_of(first, seed=SEED, n_boot=N_BOOT)
    return Scored(row_counts(windowed, at, option, lay), lay)


def value_of(scored_: Scored, option: Option) -> dict[str, Any]:
    """Net value per 100 steps with its task-bootstrap interval, plus the secondary rates."""
    return scored(scored_.counts, option.value, scored_.layout.draws)


def difference(first: Scored, second: Scored, option: Option) -> dict[str, Any]:
    """Paired `first` minus `second` and its standing (better, tie, worse)."""
    if first.counts.shape != second.counts.shape:
        raise ValueError("rows counted on different tasks cannot be paired")
    interval = gap(first.counts, second.counts, option.value, first.layout.draws)
    return {**interval, "standing": standing(interval)}


def net(scored_: Scored, option: Option) -> float:
    """Point net value per 100 steps."""
    return float(value_of(scored_, option)[NET]["value"])


def share_recovered(fine_tuned: float, broad: float, in_domain: float) -> float | None:
    """Share of the in-domain gain a fine-tune recovers; None when there is no gain to recover."""
    room = in_domain - broad
    if room <= 0:
        return None
    return (fine_tuned - broad) / room
