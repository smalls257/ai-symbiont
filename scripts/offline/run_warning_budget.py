"""Exploratory warning-budget run (Task 14c). Periphery script.

Violation prevented: **Silent Fallback** at the claim level. The analysis
(prereg/2026-10-28-warning-budget-exploratory.md, frozen first, EXPLORATORY /
POST-HOC) cannot change the G6 verdict. This script replays the same learners
on the same split as `run_selection.py`, reads the G6 settings from its results
file, and hands the risk traces to the tested pure code in
`symbiont.eval.warning_budget_report`. It loads, schedules and writes; it
chooses no threshold itself.

    run_warning_budget.py run --data ... --meta ... --g6-results results/offline-selection.json \
        --out results/warning-budget-exploratory.json --freeze-commit <prereg commit>
    run_warning_budget.py run ... --smoke-train-only   # never touches a real test task

Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1: parallelism is by process.
"""

import argparse
import json
import logging
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.offline import ReplayContext, Start, hub_modules, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder, risk_traces
from symbiont.eval.warning_budget_report import ArmTraces, report

log = logging.getLogger("warning-budget")
PREREG = "prereg/2026-10-28-warning-budget-exploratory.md"


@dataclass(frozen=True)
class G6Settings:
    """What G6 chose on TRAIN. Risk does not depend on these (learning ignores
    flags), but the learners are rebuilt exactly as G6 built them."""

    counters_min_count: int
    fly_thresholds: dict[int, float]
    freeze_commit: str


def g6_settings(path: Path) -> G6Settings:
    """Read the chosen settings; refuse a smoke file, whose choices mean nothing."""
    document = json.loads(Path(path).read_text())
    if document.get("smoke"):
        raise ValueError(f"{path} is a smoke run; the budget analysis needs the real G6 results")
    chosen = document["calibration_train_only"]
    return G6Settings(
        counters_min_count=int(chosen["counters_min_count"]["chosen"]),
        fly_thresholds={
            int(s): float(v["chosen"]) for s, v in chosen["mushroom_threshold"].items()
        },
        freeze_commit=str(document["freeze_commit"]),
    )


def traced_job(job: tuple[str, int, float | int | None]) -> tuple[ArmTraces, float | None]:
    """Replay TRAIN online then continue through TEST, recording every risk."""
    kind, seed, param = job
    t0 = time.time()
    learner = g6.make_learner(kind, seed, param)
    train_recorder, test_recorder = RiskRecorder(learner), RiskRecorder(learner)
    ctx, order_seed = g6.CTX, g6.REPLAY_SEED
    trained = replay(train_recorder, g6.TRAIN, Start.fresh(), ctx=ctx, seed=order_seed)
    tested = replay(test_recorder, g6.TEST, trained.resume(), ctx=ctx, seed=order_seed)
    traces = ArmTraces(
        risk_traces(trained.scores, train_recorder), risk_traces(tested.scores, test_recorder)
    )
    log.info("traced %s seed=%s (%.0fs)", kind, seed, time.time() - t0)
    return traces, tested.scores.recall_at_3


def prepare_hubs(meta_path: Path, train_ids: frozenset[str]) -> tuple[ReplayContext, str]:
    """The hub checkout the G6 prereg fixes (median-created train task)."""
    meta = json.loads(Path(meta_path).read_text())
    hub_task = sel.median_task({t: m["created_at"] for t, m in meta.items()}, train_ids)
    with tempfile.TemporaryDirectory(prefix="sqlglot-hub-") as tmp:
        references = g6.checkout_references(meta[hub_task]["base_commit"], Path(tmp))
    g6.HUBS = hub_modules(references, sel.HUB_CUTOFF)
    return ReplayContext(references=references, hubs=g6.HUBS), hub_task


def trace_all_learners(settings: G6Settings, workers: int):
    """Counters first and alone (it fills the shared feature cache the forked
    workers inherit), then similarity and the three fly seeds in parallel."""
    counters = traced_job(("counters", 0, settings.counters_min_count))
    jobs = [("similarity", 0, None)] + [
        ("mushroom", s, settings.fly_thresholds[s]) for s in sel.WIRING_SEEDS
    ]
    similarity, *fly_runs = g6.pool_map(traced_job, jobs, workers)
    return counters, similarity, dict(zip(sel.WIRING_SEEDS, fly_runs, strict=True))


def provenance(args: argparse.Namespace, settings: G6Settings) -> dict[str, Any]:
    """Where the numbers came from: prereg, G6 freeze, host, settings used."""
    return {
        "exploratory": True,
        "post_hoc": True,
        "smoke": args.smoke_train_only,
        "prereg": PREREG,
        "prereg_commit": args.freeze_commit,
        "g6_prereg": "prereg/2026-10-29-offline-selection.md",
        "g6_freeze_commit": settings.freeze_commit,
        "run_host": {
            "hostname": platform.node(),
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "workers": args.workers,
        },
        "g6_settings": {
            "counters_min_count": settings.counters_min_count,
            "fly_thresholds": {str(s): v for s, v in settings.fly_thresholds.items()},
        },
    }


def run(args: argparse.Namespace) -> None:
    """Replay, report, write."""
    t_start = time.time()
    settings = g6_settings(Path(args.g6_results))
    g6.TRAIN, g6.TEST, train_ids, test_ids, counts = g6.prepare_sessions(
        Path(args.data), smoke=args.smoke_train_only
    )
    g6.CTX, hub_task = prepare_hubs(Path(args.meta), train_ids)
    counters, similarity, flies = trace_all_learners(settings, args.workers)
    result = report(counters[0], {s: arm for s, (arm, _) in flies.items()}, seed=sel.SEED)
    for line in result["table_rows"]:
        log.info(line)
    document: dict[str, Any] = {
        **provenance(args, settings),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "wall_clock_s": time.time() - t_start,
        "data": {
            **counts,
            "tasks_train": len(train_ids),
            "tasks_test": len(test_ids),
            "hub_task": hub_task,
        },
        "similarity": {
            "arm": "similarity",
            "role": "reference",
            "split": "test",
            "note": "no flags (recall only)",
            "recall_at_3": similarity[1],
        },
        **result,
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - t_start)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_parser = sub.add_parser("run")
    for name in ("data", "meta", "g6-results", "out", "freeze-commit"):
        run_parser.add_argument(f"--{name}", required=True)
    run_parser.add_argument("--workers", type=int, default=4)
    run_parser.add_argument("--smoke-train-only", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(args)


if __name__ == "__main__":
    main()
