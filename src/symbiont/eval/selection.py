"""The pure decisions of the offline selection run (G6), fixed in the prereg.

Violation prevented: **Silent Fallback** and **Forensic Coding** in the run
script. Every rule the prereg states (replay order, which task gives the hub
checkout, which grid value wins, what the results file holds) is a named,
tested function here, so the periphery script only fetches, clones and
schedules; it cannot quietly choose a different rule. Nothing here reads a
file, a clock or a network (**Infected Core** guard).
"""

import random
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from symbiont.eval.offline import OfflineScores
from symbiont.eval.offline_table import FLAG_COLUMN
from symbiont.eval.offline_verdict import Verdict, bootstrap_auroc_interval
from symbiont.records.schema import Record

SEED = 20261029
TEST_FRACTION = 0.3
HUB_CUTOFF = 0.5
COUNTERS_MIN_COUNTS = (1, 2, 3, 4)
MUSHROOM_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
WIRING_SEEDS = (0, 1, 2)
LEARNING_RATE = 0.1


def group_sessions(records: Sequence[Record]) -> list[list[Record]]:
    """Records of one session are contiguous in the reader's output."""
    sessions: dict[str, list[Record]] = {}
    for record in records:
        sessions.setdefault(record.session_id, []).append(record)
    return list(sessions.values())


def replay_order(
    sessions: Sequence[Sequence[Record]], *, seed: int = SEED
) -> list[Sequence[Record]]:
    """Sessions sorted by (seeded shuffle rank of the task id, session id).

    The attempts of one task sit together but tasks come in no calendar order.
    """
    # key=str only satisfies the type checker (task_id is optional); ids are strings
    task_ids = sorted({sess[0].task_id for sess in sessions}, key=str)
    random.Random(seed).shuffle(task_ids)
    rank = {task: i for i, task in enumerate(task_ids)}
    return sorted(sessions, key=lambda sess: (rank[sess[0].task_id], sess[0].session_id))


def median_task(created_at: Mapping[str, str], tasks: frozenset[str]) -> str:
    """The task with the median `created_at` among `tasks`.

    An even count takes the earlier middle one, equal dates break by instance id.
    """
    missing = sorted(task for task in tasks if task not in created_at)
    if missing:
        raise ValueError(f"no created_at for {len(missing)} train task(s), e.g. {missing[:3]}")
    ordered = sorted(tasks, key=lambda task: (created_at[task], task))
    return ordered[(len(ordered) - 1) // 2]


def pick_best[T](grid: Sequence[T], score: Callable[[T], float]) -> tuple[T, dict[T, float]]:
    """Highest score wins; ties go to the first value listed."""
    scores = {value: score(value) for value in grid}
    best = grid[0]
    for value in grid:
        if scores[value] > scores[best]:
            best = value
    return best, scores


def row_summary(label: str, runs: Sequence[OfflineScores], *, seed: int = SEED) -> dict[str, Any]:
    """One table row for the results file.

    Balanced accuracy with its descriptive interval, recall@3 (mean over runs
    that recalled) and flag rate.
    """
    value, low, high = bootstrap_auroc_interval(runs, seed=seed)
    recalls = [r.recall_at_3 for r in runs if r.recall_at_3 is not None]
    steps = runs[0].n_steps
    flagged = sum(f for s in runs[0].per_session for f in s.flagged)
    return {
        "label": label,
        FLAG_COLUMN: value,
        "ci95_low": low,
        "ci95_high": high,
        "recall_at_3": sum(recalls) / len(recalls) if recalls else None,
        "steps": steps,
        "flag_rate": flagged / steps,
    }


def per_step_bits(scores: OfflineScores) -> list[dict[str, Any]]:
    """The per-step data the prereg promises.

    For every test session, one character per step for the label and for the flag.
    """
    return [
        {
            "task_id": s.task_id,
            "followed": "".join("1" if f else "0" for f in s.followed),
            "flagged": "".join("1" if f else "0" for f in s.flagged),
        }
        for s in scores.per_session
    ]


def verdict_record(verdict: Verdict, *, margin: float) -> dict[str, Any]:
    """The G6 verdict as it is written to the results file, with the rule in words."""
    return {
        "live_learner": verdict.live,
        "gap_fly_minus_counters": verdict.gap,
        "gap_ci95_low": verdict.ci_low,
        "gap_ci95_high": verdict.ci_high,
        "margin": margin,
        "rule": "fly iff round(gap, 12) >= margin and ci95_low > 0, else counters",
    }
