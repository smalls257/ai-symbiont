"""Penalized offline selection run (T36). Periphery script.

The rules live in `symbiont.eval.net_benefit` and `penalized_report` (pure, tested) and
prereg/2026-10-28-penalized-selection.md; this script loads data, schedules replays and
writes results, choosing no threshold. Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1.
Usage: run_penalized.py run --data ... --meta ... --out ... --scored --prereg ...
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_selection as g6

from symbiont.core.counters import Counters
from symbiont.core.dense import DenseNet
from symbiont.core.mushroom import Mushroom
from symbiont.core.similarity import Similarity
from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import DENSE_LEARNING_RATES, PRIMARY_COST
from symbiont.eval.offline import Start, replay
from symbiont.eval.penalized_report import report
from symbiont.eval.prereg_git import run_provenance
from symbiont.eval.selection_record import hub_record
from symbiont.eval.warning_budget_metrics import RiskRecorder, risk_traces
from symbiont.eval.warning_budget_report import ArmTraces

log = logging.getLogger("penalized-selection")
PREREG_NAME = "2026-10-28-penalized-selection.md"
Job = tuple[str, int, float | None]


def make_learner(kind: str, seed: int, param: float | None):
    """The learner of one job; `param` is DenseNet's readout learning rate."""
    if kind == "counters":
        return Counters(min_count=1, hubs=g6.HUBS)
    if kind == "similarity":
        return Similarity()
    if kind == "mushroom":
        return Mushroom(seed, lr=sel.LEARNING_RATE, hubs=g6.HUBS)
    if kind == "dense" and param is not None:
        return DenseNet(seed, lr=param, hubs=g6.HUBS)
    raise ValueError(f"unknown learner {kind!r} with parameter {param!r}")


def traced_job(job: Job) -> tuple[ArmTraces, float | None]:
    """Replay TRAIN online then continue through TEST, recording every risk."""
    kind, seed, param = job
    started = time.time()
    learner = make_learner(kind, seed, param)
    train_recorder, test_recorder = RiskRecorder(learner), RiskRecorder(learner)
    ctx, order_seed = g6.CTX, g6.REPLAY_SEED
    trained = replay(train_recorder, g6.TRAIN, Start.fresh(), ctx=ctx, seed=order_seed)
    tested = replay(test_recorder, g6.TEST, trained.resume(), ctx=ctx, seed=order_seed)
    traces = ArmTraces(
        risk_traces(trained.scores, train_recorder), risk_traces(tested.scores, test_recorder)
    )
    log.info("traced %s seed=%s param=%s (%.0fs)", kind, seed, param, time.time() - started)
    return traces, tested.scores.recall_at_3


def trace_all(workers: int):
    """Counters first and alone (it fills the feature cache the forked workers inherit)."""
    counters = traced_job(("counters", 0, None))
    jobs: list[Job] = [("similarity", 0, None)]
    jobs += [("mushroom", s, None) for s in sel.WIRING_SEEDS]
    jobs += [("dense", s, lr) for s in sel.WIRING_SEEDS for lr in DENSE_LEARNING_RATES]
    results = dict(zip(jobs, g6.pool_map(traced_job, jobs, workers), strict=True))
    return counters, results


def recall_record(counters: tuple, results: dict[Job, tuple]) -> dict[str, float | None]:
    """Recall@3 of every replay that recalls, keyed by a short label."""
    pairs = [("counters", counters[1])] + [
        (f"{k} seed {s}" + (f" lr {p:g}" if p else ""), v[1]) for (k, s, p), v in results.items()
    ]
    return dict(pairs)


def git_head() -> str:
    """The commit of the code that ran, so the results name it."""
    root = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def similarity_row(recall: float | None) -> dict[str, Any]:
    """Similarity never warns: net benefit 0 by construction, recall only."""
    return {
        "arm": "similarity",
        "role": "reference",
        "split": "test",
        "cost": None,
        "note": "no risk score, warns never; net benefit 0 by construction",
        "recall_at_3": recall,
    }


def _test_steps(counters: tuple) -> int:
    return sum(len(trace.followed) for trace in counters[0].test)


def results_document(
    args: argparse.Namespace, label: dict[str, str | None], data: tuple, started: float
) -> dict[str, Any]:
    """Provenance, host, split sizes and hub checkout of the run."""
    hub, counts, train_ids, test_ids = data
    return {
        "smoke": args.smoke_train_only,
        **label,
        "code_commit": git_head(),
        "g6_prereg": "prereg/2026-10-29-offline-selection.md",
        "run_host": g6.run_host_record(args.workers),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "wall_clock_s": time.time() - started,
        "learning_false_alarm_cost": PRIMARY_COST,
        "data": {
            **counts,
            "tasks_train": len(train_ids),
            "tasks_test": len(test_ids),
            "sessions_train": len(g6.TRAIN),
            "sessions_test": len(g6.TEST),
            "split_seed": sel.SEED,
            "test_fraction": sel.TEST_FRACTION,
        },
        "hub_checkout": hub_record(hub, g6.HUBS),
    }


def run(args: argparse.Namespace) -> None:
    """Replay every learner once, apply the registered choices and rule, write the results."""
    started = time.time()
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=PREREG_NAME)
    meta = json.loads(Path(args.meta).read_text())
    g6.TRAIN, g6.TEST, train_ids, test_ids, counts = g6.prepare_sessions(
        Path(args.data), smoke=args.smoke_train_only
    )
    hub = g6.prepare_hubs(meta, train_ids)
    g6.CTX.false_alarm_cost = PRIMARY_COST
    counters, results = trace_all(args.workers)
    flies = {s: results[("mushroom", s, None)][0] for s in sel.WIRING_SEEDS}
    dense = {
        s: {lr: results[("dense", s, lr)][0] for lr in DENSE_LEARNING_RATES}
        for s in sel.WIRING_SEEDS
    }
    body = report(counters[0], flies, dense, seed=sel.SEED)
    body["rows"].append(similarity_row(results[("similarity", 0, None)][1]))
    for line in body["table_rows"]:
        log.info(line)
    log.info("verdict: %s", body["verdict"]["live_warner"])
    document = results_document(args, label, (hub, counts, train_ids, test_ids), started)
    document.update(
        recall_at_3=recall_record(counters, results), **body, steps_test=_test_steps(counters)
    )
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - started)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_parser = sub.add_parser("run")
    for name in ("data", "meta", "out"):
        run_parser.add_argument(f"--{name}", required=True)
    run_parser.add_argument("--scored", action="store_true")
    run_parser.add_argument("--prereg")
    run_parser.add_argument("--workers", type=int, default=14)
    run_parser.add_argument("--smoke-train-only", action="store_true")
    args = parser.parse_args(argv)
    if args.scored and args.smoke_train_only:
        parser.error("--smoke-train-only never produces a scored result; drop one of the two")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(args)


if __name__ == "__main__":
    main()
