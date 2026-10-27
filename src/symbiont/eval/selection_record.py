"""The sections of the offline-selection results file, built from plain values.

Violation prevented: **Silent Fallback** in the run script. What the results
file records (grid scores, the chosen values, row labels, hub checkout, split
sizes) is fixed here as named, tested functions, so the periphery script only
passes numbers in and writes JSON out; it cannot quietly leave a section out
or relabel a row. Nothing here reads a file, a clock or a network
(**Infected Core** guard).
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from symbiont.eval import selection as sel
from symbiont.eval.offline import OfflineScores


@dataclass(frozen=True)
class HubCheckout:
    """The prereg's hub checkout: the median-created train task's base commit."""

    task_id: str
    created_at: str
    base_commit: str
    reference_files: int


@dataclass(frozen=True)
class Calibration:
    """Grid scores on TRAIN only and the value each rule picked."""

    counters_scores: dict[int, float]
    best_min_count: int
    fly_scores: dict[tuple[str, int, float], float]
    best_threshold: dict[int, float]


@dataclass(frozen=True)
class FinalScores:
    """TEST scores of every arm, from the calibrated settings."""

    counters: OfflineScores
    similarity: OfflineScores
    flies: dict[int, OfflineScores]


def result_rows(final: FinalScores) -> dict[str, dict[str, Any]]:
    """The results-file rows, each labelled reference or under test."""
    return {
        "counters": sel.row_summary("reference", [final.counters]),
        "similarity": sel.row_summary("reference", [final.similarity]),
        "fly": sel.row_summary(
            "under test, seed-averaged over wiring seeds 0-2 (the row the G6 rule uses)",
            list(final.flies.values()),
        ),
        **{
            f"fly seed {seed}": sel.row_summary(f"under test, wiring seed {seed}", [scores])
            for seed, scores in final.flies.items()
        },
    }


def calibration_record(cal: Calibration) -> dict[str, Any]:
    """The calibration section: every grid score and the value chosen."""
    return {
        "counters_min_count": {
            "scores": {str(k): v for k, v in cal.counters_scores.items()},
            "chosen": cal.best_min_count,
        },
        "mushroom_threshold": {
            str(seed): {
                "scores": {
                    str(thr): cal.fly_scores[("mushroom", seed, thr)]
                    for thr in sel.MUSHROOM_THRESHOLDS
                },
                "chosen": cal.best_threshold[seed],
            }
            for seed in sel.WIRING_SEEDS
        },
        "learning_rate": sel.LEARNING_RATE,
    }


def split_record(
    counts: dict[str, int], *, tasks: tuple[int, int], sessions: tuple[int, int], steps_test: int
) -> dict[str, Any]:
    """What was read and how it split; `tasks` and `sessions` are (train, test) sizes."""
    return {
        **counts,
        "tasks_train": tasks[0],
        "tasks_test": tasks[1],
        "sessions_train": sessions[0],
        "sessions_test": sessions[1],
        "steps_test": steps_test,
        "split_seed": sel.SEED,
        "test_fraction": sel.TEST_FRACTION,
    }


def hub_record(hub: HubCheckout, hub_modules: Collection[str]) -> dict[str, Any]:
    """The hub-checkout section: which task, which commit, which modules counted as hubs."""
    return {
        "task_id": hub.task_id,
        "created_at": hub.created_at,
        "base_commit": hub.base_commit,
        "cutoff": sel.HUB_CUTOFF,
        "hub_modules": sorted(hub_modules),
        "reference_files": hub.reference_files,
    }


def per_step_record(final: FinalScores) -> dict[str, Any]:
    """Per-step label and flag bits for every arm, as the prereg promises."""
    return {
        "counters": sel.per_step_bits(final.counters),
        "similarity": sel.per_step_bits(final.similarity),
        **{f"fly seed {seed}": sel.per_step_bits(run) for seed, run in final.flies.items()},
    }
