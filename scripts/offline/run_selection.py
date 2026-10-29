"""Offline selection run (Task 14 part 2, the G6 gate). Periphery script.

The rules are fixed by prereg/2026-10-29-offline-selection.md and live in `symbiont.eval.selection`
and `offline` (pure, tested). This script fetches metadata, schedules replays and writes results;
a failed worker or a missing created_at stops the run, nothing is defaulted.
Usage: run_selection.py {fetch-meta|run} ... (run without --scored is exploratory)
"""

import argparse
import json
import logging
import multiprocessing as mp
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from symbiont.core.counters import Counters
from symbiont.core.mushroom import Mushroom
from symbiont.core.similarity import Similarity
from symbiont.eval import selection as sel
from symbiont.eval.offline import (
    OfflineScores,
    ReplayContext,
    Start,
    drop_taskless,
    hub_modules,
    replay,
    split_by_task,
)
from symbiont.eval.offline_table import render_table
from symbiont.eval.offline_verdict import MARGIN, Verdict, fly_default
from symbiont.eval.prereg_git import run_provenance
from symbiont.eval.selection_record import (
    Calibration,
    FinalScores,
    HubCheckout,
    calibration_record,
    hub_record,
    per_step_record,
    result_rows,
    split_record,
)
from symbiont.readers import openhands
from symbiont.store.references import build_references

log = logging.getLogger("offline-selection")

SWE_REBENCH = "hf://datasets/nebius/SWE-rebench/data/{}.parquet"
SWE_REBENCH_FILES = ("filtered-00000-of-00001", "test-00001-of-00002")
SQLGLOT_URL = "https://github.com/tobymao/sqlglot"
REPLAY_SEED = 0
PREREG_NAME = "2026-10-29-offline-selection.md"
BACKOFF_SECONDS = (5, 15, 45, 120, 300)


class RateLimitedError(RuntimeError):
    """Hugging Face kept answering 429 through every wait."""


def with_backoff[T](call: Callable[[], T], *, sleep: Callable[[float], None] = time.sleep) -> T:
    """Retry a Hugging Face read on HTTP 429 with growing waits.

    After the last wait, fail saying so rather than returning partial metadata.
    """
    for wait in BACKOFF_SECONDS:
        try:
            return call()
        except Exception as exc:  # duckdb raises its own HTTPException; only 429 is retried
            if "429" not in str(exc):
                raise
            log.warning("Hugging Face answered 429 (rate limited); waiting %ss", wait)
            sleep(wait)
    try:
        return call()
    except Exception as exc:
        if "429" in str(exc):
            raise RateLimitedError(
                f"Hugging Face still answers 429 after {len(BACKOFF_SECONDS)} waits "
                f"({sum(BACKOFF_SECONDS)}s). Wait a few minutes or put a token in "
                "~/.cache/huggingface/token."
            ) from exc
        raise


def fetch_meta(data: Path, out: Path) -> None:
    import duckdb

    task_ids = sorted(
        {sess[0].task_id for sess in sel.group_sessions(list(openhands.read(data, "sqlglot")))}
    )
    token = Path.home() / ".cache/huggingface/token"
    con = duckdb.connect()
    if token.exists():
        con.sql(f"CREATE SECRET hf (TYPE HUGGINGFACE, TOKEN '{token.read_text().strip()}')")
    meta: dict[str, dict[str, str]] = {}
    for name in SWE_REBENCH_FILES:
        rows = with_backoff(
            lambda file=name: con.execute(
                "SELECT instance_id, CAST(created_at AS VARCHAR), base_commit "
                f"FROM '{SWE_REBENCH.format(file)}' "
                "WHERE instance_id LIKE 'tobymao__sqlglot%'"
            ).fetchall()
        )
        for iid, created, commit in rows:
            meta.setdefault(iid, {"created_at": created, "base_commit": commit})
    missing = [task for task in task_ids if task not in meta]
    if missing:
        raise SystemExit(f"{len(missing)} task(s) have no SWE-rebench row, e.g. {missing[:3]}")
    out.write_text(json.dumps({task: meta[task] for task in task_ids}, indent=1, sort_keys=True))
    log.info("wrote %d tasks of metadata to %s", len(task_ids), out)


def checkout_references(commit: str, workdir: Path) -> dict[str, frozenset[str]]:
    # Fetch by hash: a base_commit can be off every branch (a rebased PR), so a clone +
    # checkout misses it.
    dest = workdir / "sqlglot"
    dest.mkdir()
    for step in (
        ["init", "--quiet"],
        ["remote", "add", "origin", SQLGLOT_URL],
        ["fetch", "--quiet", "--depth", "1", "origin", commit],
        ["checkout", "--quiet", "FETCH_HEAD"],
    ):
        subprocess.run(["git", "-C", str(dest), *step], check=True)
    return build_references(dest)


# --- learners and replays; module-level state is inherited by forked workers ---
CTX: ReplayContext | None = None
TRAIN: list = []
TEST: list = []
HUBS: frozenset[str] = frozenset()


def make_learner(kind: str, seed: int = 0, param: float | int | None = None):
    """The learner for one grid cell: `param` is min_count (counters) or threshold (mushroom)."""
    if kind == "counters":
        return Counters(min_count=int(param), hubs=HUBS)
    if kind == "similarity":
        return Similarity()
    return Mushroom(seed, lr=sel.LEARNING_RATE, trouble_threshold=float(param), hubs=HUBS)


def calibrate_job(job: tuple[str, int, float | int]) -> tuple[tuple[str, int, float | int], float]:
    """Replay TRAIN for one grid cell and return its balanced accuracy."""
    kind, seed, param = job
    started = time.time()
    result = replay(
        make_learner(kind, seed, param), TRAIN, Start.fresh(), ctx=CTX, seed=REPLAY_SEED
    )
    log.info(
        "calibration %s seed=%s param=%s train balanced accuracy %.4f (%.0fs)",
        kind,
        seed,
        param,
        result.scores.auroc,
        time.time() - started,
    )
    return job, result.scores.auroc


def final_job(job: tuple[str, int, float | int | None]) -> OfflineScores:
    """Train online on TRAIN, then continue through TEST; return the TEST scores."""
    kind, seed, param = job
    started = time.time()
    learner = make_learner(kind, seed, param)
    trained = replay(learner, TRAIN, Start.fresh(), ctx=CTX, seed=REPLAY_SEED)
    tested = replay(learner, TEST, trained.resume(), ctx=CTX, seed=REPLAY_SEED)
    log.info("final %s seed=%s param=%s done (%.0fs)", kind, seed, param, time.time() - started)
    return tested.scores


def pool_map(fn, jobs, workers: int):
    """Map `fn` over `jobs` in forked workers so they inherit the module-level state.

    A worker that dies raises BrokenProcessPool here; `multiprocessing.Pool` would hang.
    """
    context = mp.get_context("fork")
    with ProcessPoolExecutor(min(workers, len(jobs)), mp_context=context) as executor:
        return list(executor.map(fn, jobs))


def prepare_sessions(data: Path, *, smoke: bool):
    """Read, split and order the sessions; smoke keeps only train-split tasks."""
    records = list(openhands.read(data, "sqlglot"))
    sessions, dropped = drop_taskless(sel.group_sessions(records))
    train_ids, test_ids = split_by_task(
        [sess[0].task_id for sess in sessions], test_fraction=sel.TEST_FRACTION, seed=sel.SEED
    )
    counts = {
        "records": len(records),
        "sessions_read": len(sessions) + dropped,
        "sessions_dropped_taskless": dropped,
    }
    if smoke:
        keep = sorted(train_ids)[:24]
        sessions = [sess for sess in sessions if sess[0].task_id in set(keep)]
        train_ids, test_ids = split_by_task(keep, test_fraction=sel.TEST_FRACTION, seed=sel.SEED)
        log.warning("SMOKE: only train-split tasks are used; no real test task is read")
    ordered = sel.replay_order(sessions)
    train = [sess for sess in ordered if sess[0].task_id in train_ids]
    test = [sess for sess in ordered if sess[0].task_id in test_ids]
    return train, test, train_ids, test_ids, counts


def prepare_hubs(meta: dict, train_ids: frozenset[str]) -> HubCheckout:
    """Clone the hub task's base commit and set HUBS and CTX for the replays."""
    global CTX, HUBS
    hub_task = sel.median_task({task: m["created_at"] for task, m in meta.items()}, train_ids)
    commit = meta[hub_task]["base_commit"]
    with tempfile.TemporaryDirectory(prefix="sqlglot-hub-") as tmp:
        references = checkout_references(commit, Path(tmp))
    HUBS = hub_modules(references, sel.HUB_CUTOFF)
    log.info("hub checkout: task %s at %s; hubs %s", hub_task, commit, sorted(HUBS))
    CTX = ReplayContext(references=references, hubs=HUBS)
    return HubCheckout(hub_task, meta[hub_task]["created_at"], commit, len(references))


def calibrate(workers: int, timings: dict[str, float]) -> Calibration:
    """Pick counters min_count and each wiring seed's threshold on TRAIN, as the prereg fixes."""
    started = time.time()
    counters_scores = {}
    for min_count in sel.COUNTERS_MIN_COUNTS:  # serial: the first pass also fills the feature cache
        counters_scores[min_count] = calibrate_job(("counters", 0, min_count))[1]
    best_min_count, _ = sel.pick_best(sel.COUNTERS_MIN_COUNTS, counters_scores.__getitem__)
    timings["counters_calibration_and_features_s"] = time.time() - started

    started = time.time()
    jobs = [("mushroom", seed, thr) for seed in sel.WIRING_SEEDS for thr in sel.MUSHROOM_THRESHOLDS]
    fly_scores = dict(pool_map(calibrate_job, jobs, workers))
    best_threshold = {}
    for seed in sel.WIRING_SEEDS:
        best_threshold[seed], _ = sel.pick_best(
            sel.MUSHROOM_THRESHOLDS, lambda thr, seed=seed: fly_scores[("mushroom", seed, thr)]
        )
    timings["mushroom_calibration_s"] = time.time() - started
    log.info(
        "calibrated on TRAIN only: counters min_count=%s; mushroom thresholds %s",
        best_min_count,
        best_threshold,
    )
    return Calibration(counters_scores, best_min_count, fly_scores, best_threshold)


def final_replays(cal: Calibration, workers: int, timings: dict[str, float]) -> FinalScores:
    """Replay every arm through TRAIN then TEST with the calibrated settings."""
    started = time.time()
    # the counters run goes first: it fills the test-step features for the pool
    counters = final_job(("counters", 0, cal.best_min_count))
    similarity = final_job(("similarity", 0, None))
    timings["counters_similarity_final_s"] = time.time() - started
    started = time.time()
    fly_runs = pool_map(
        final_job, [("mushroom", s, cal.best_threshold[s]) for s in sel.WIRING_SEEDS], workers
    )
    timings["mushroom_final_s"] = time.time() - started
    return FinalScores(counters, similarity, dict(zip(sel.WIRING_SEEDS, fly_runs, strict=True)))


def run_host_record(workers: int) -> dict[str, Any]:
    """Where and with what the run happened."""
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "workers": workers,
    }


@dataclass(frozen=True)
class Outcome:
    """Everything one selection run produced, ready to be written as the results file."""

    hub: HubCheckout
    cal: Calibration
    final: FinalScores
    verdict: Verdict
    table: str
    counts: dict[str, int]
    task_split: tuple[frozenset[str], frozenset[str]]
    timings: dict[str, float]


def results_document(
    args: argparse.Namespace, out: Outcome, run_started: float, provenance: dict[str, str | None]
) -> dict[str, Any]:
    """The results file: sections in the order the prereg lists them."""
    train_ids, test_ids = out.task_split
    return {
        "smoke": args.smoke_train_only,
        **provenance,
        "run_host": run_host_record(args.workers),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "wall_clock_s": time.time() - run_started,
        "timings": out.timings,
        "data": split_record(
            out.counts,
            tasks=(len(train_ids), len(test_ids)),
            sessions=(len(TRAIN), len(TEST)),
            steps_test=out.final.counters.n_steps,
        ),
        "replay_order": {
            "seed": sel.SEED,
            "train_tasks": _task_order(TRAIN),
            "test_tasks": _task_order(TEST),
        },
        "hub_checkout": hub_record(out.hub, HUBS),
        "calibration_train_only": calibration_record(out.cal),
        "rows": result_rows(out.final),
        "table_markdown": out.table,
        "g6": sel.verdict_record(out.verdict, margin=MARGIN),
        "per_step": per_step_record(out.final),
    }


def run(args: argparse.Namespace) -> None:
    """Calibrate on TRAIN, replay TEST once, apply the registered rule, write the results file."""
    global TRAIN, TEST
    run_started = time.time()
    provenance = run_provenance(scored=args.scored, prereg=args.prereg, expects=PREREG_NAME)
    meta = json.loads(Path(args.meta).read_text())
    TRAIN, TEST, train_ids, test_ids, counts = prepare_sessions(
        Path(args.data), smoke=args.smoke_train_only
    )
    log.info("train: %d tasks; test: %d tasks", len(train_ids), len(test_ids))
    hub = prepare_hubs(meta, train_ids)
    timings: dict[str, float] = {}
    cal = calibrate(args.workers, timings)
    final = final_replays(cal, args.workers, timings)

    verdict = fly_default(list(final.flies.values()), final.counters, seed=sel.SEED)
    table = render_table(
        {"counters": final.counters, "similarity": final.similarity}, fly_seeds=final.flies
    )
    log.info("\n%s", table)
    log.info("G6: %s", sel.verdict_record(verdict, margin=MARGIN))
    outcome = Outcome(hub, cal, final, verdict, table, counts, (train_ids, test_ids), timings)
    Path(args.out).write_text(
        json.dumps(results_document(args, outcome, run_started, provenance), indent=1)
    )
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - run_started)


def _task_order(sessions) -> list[str]:
    seen: list[str] = []
    for session in sessions:
        if not seen or seen[-1] != session[0].task_id:
            seen.append(session[0].task_id)
    return seen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    fetch = sub.add_parser("fetch-meta")
    fetch.add_argument("--data", required=True)
    fetch.add_argument("--out", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--data", required=True)
    run_cmd.add_argument("--meta", required=True)
    run_cmd.add_argument("--out", required=True)
    run_cmd.add_argument("--scored", action="store_true")
    run_cmd.add_argument("--prereg")
    run_cmd.add_argument("--workers", type=int, default=21)
    run_cmd.add_argument("--smoke-train-only", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "run" and args.scored and args.smoke_train_only:
        parser.error("--smoke-train-only never produces a scored result; drop one of the two")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    if args.cmd == "fetch-meta":
        fetch_meta(Path(args.data), Path(args.out))
    else:
        run(args)


if __name__ == "__main__":
    main()
