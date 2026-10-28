"""Scored T46 run on the held-out repositories (prereg/2026-10-28-note-cost.md). Periphery.

The registered rules live in `symbiont.eval.note_cost_scored` and `note_cost_scored_report`
(pure, tested). This script loads Pillow, dvc and conan, splits each by task, checks out each
repository's hub commit, replays every learner (TRAIN online, then TEST online), fits the
classifier, and writes the results file. It chooses nothing itself.

    run_note_cost_scored.py split --data-dir data/nebius-openhands/held-out
    run_note_cost_scored.py run --data-dir data/nebius-openhands/held-out \
        --pool results/repo-pool.json --pool-dir data/nebius-openhands/pool \
        --out results/note-cost.json --scored --prereg prereg/2026-10-28-note-cost.md

At most half the CPU (16 workers). Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1.
"""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import run_note_cost as nc
import run_repo_curve as rc
import run_selection as g6
from export_nebius_repos import TRAJECTORIES_REVISION

from symbiont.core.counters import Counters
from symbiont.core.dense import DenseNet
from symbiont.core.mushroom import Mushroom
from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import DENSE_LEARNING_RATES, PRIMARY_COST
from symbiont.eval.note_cost_logistic import (
    L2_GRID,
    Steps,
    fit_logistic,
    out_of_fold_risks,
    predict,
)
from symbiont.eval.note_cost_scored_report import scored_report
from symbiont.eval.note_cost_select import task_folds
from symbiont.eval.note_delivery import NoteTrace, boundary_steps
from symbiont.eval.offline import (
    History,
    ReplayContext,
    Start,
    drop_taskless,
    hub_modules,
    replay,
    split_by_task,
)
from symbiont.eval.prereg_git import run_provenance
from symbiont.eval.repo_pool import HELD_OUT
from symbiont.eval.warning_budget_metrics import RiskRecorder
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError
from symbiont.store.references import build_references

log = logging.getLogger("note-cost-scored")
PREREG_NAME = "2026-10-28-note-cost.md"
WORKERS_CAP = 16  # half the run host's cores: T39 and a fly study share the CPU
HUB_CUTOFF = 0.5
REPO: dict[str, dict[str, Any]] = {}  # held-out repository -> sessions, ctx, columns
Job = tuple[str, int, float | None, str]


def file_of(data_dir: Path, repo: str, suffix: str = ".jsonl") -> Path:
    """The exported file of one repository."""
    return data_dir / (repo.replace("/", "__") + suffix)


SMOKE_TASKS = 12


def split_repo(data_dir: Path, repo: str, *, smoke: bool = False) -> dict[str, Any]:
    """Sessions of one repository split by task (test fraction 0.3, seed 20261029).

    Smoke keeps a few TRAIN-split tasks and splits them again: no real TEST task is replayed.
    """
    records, refused = readable_records(file_of(data_dir, repo), repo)
    sessions, dropped = drop_taskless(sel.group_sessions(records))
    train_ids, test_ids = split_by_task(
        [s[0].task_id for s in sessions], test_fraction=sel.TEST_FRACTION, seed=sel.SEED
    )
    if smoke:
        keep = set(sorted(train_ids)[:SMOKE_TASKS])
        sessions = [s for s in sessions if s[0].task_id in keep]
        train_ids, test_ids = split_by_task(
            sorted(keep), test_fraction=sel.TEST_FRACTION, seed=sel.SEED
        )
    ordered = sel.replay_order(sessions)
    return {
        "train": [s for s in ordered if s[0].task_id in train_ids],
        "test": [s for s in ordered if s[0].task_id in test_ids],
        "train_ids": train_ids,
        "dropped_taskless": dropped,
        "refused_by_reader": refused,
    }


def readable_records(path: Path, repo: str) -> tuple[list, int]:
    """Records of every row the reader reads; refused rows are dropped, counted and logged."""
    records, refused = [], 0
    for row in openhands.read_each_row(path, repo):
        if isinstance(row, ReadError):
            refused += 1
            log.warning("dropped a trajectory the reader refuses (prereg rule): %s", row)
            continue
        records += row
    return records, refused


def split_counts(parts: dict[str, Any]) -> dict[str, int]:
    """Tasks, sessions and steps per split: counts only, no label and no metric."""
    found = {
        "sessions_dropped_taskless": parts["dropped_taskless"],
        "trajectories_refused_by_reader": parts["refused_by_reader"],
    }
    for name in ("train", "test"):
        found[f"tasks_{name}"] = len({s[0].task_id for s in parts[name]})
        found[f"sessions_{name}"] = len(parts[name])
        found[f"steps_{name}"] = sum(len(s) for s in parts[name])
    return found


def split(args: argparse.Namespace) -> None:
    """Print the per-split counts the prereg records before any metric exists."""
    counts = {repo: split_counts(split_repo(Path(args.data_dir), repo)) for repo in HELD_OUT}
    print(json.dumps(counts, indent=1))


def hub_context(data_dir: Path, repo: str, train_ids: frozenset[str]) -> tuple[ReplayContext, dict]:
    """Check out the median-created TRAIN task's base commit and build the replay context."""
    meta = json.loads(file_of(data_dir, repo, ".meta.json").read_text())
    task = sel.median_task({t: m["created_at"] for t, m in meta.items()}, train_ids)
    commit = meta[task]["base_commit"]
    with tempfile.TemporaryDirectory(prefix="hub-") as tmp:
        references = checkout_references(repo, commit, Path(tmp))
    hubs = hub_modules(references, HUB_CUTOFF)
    log.info("%s hub checkout: task %s at %s; hubs %s", repo, task, commit, sorted(hubs))
    ctx = ReplayContext(references=references, hubs=hubs, false_alarm_cost=PRIMARY_COST)
    return ctx, {
        "task_id": task,
        "base_commit": commit,
        "hub_modules": sorted(hubs),
        "reference_files": len(references),
    }


def checkout_references(repo: str, commit: str, workdir: Path) -> dict[str, frozenset[str]]:
    """Fetch one commit by hash (it may be off every branch) and map test references."""
    dest = workdir / "checkout"
    dest.mkdir()
    for step in (
        ["init", "--quiet"],
        ["remote", "add", "origin", f"https://github.com/{repo}"],
        ["fetch", "--quiet", "--depth", "1", "origin", commit],
        ["checkout", "--quiet", "FETCH_HEAD"],
    ):
        subprocess.run(["git", "-C", str(dest), *step], check=True)
    return build_references(dest)


def learner(kind: str, seed: int, param: float | None, hubs: frozenset[str]) -> Any:
    """One registered learner; `param` is DenseNet's readout rate."""
    if kind == "counters":
        return Counters(min_count=1, hubs=hubs)
    if kind == "mushroom":
        return Mushroom(seed, lr=sel.LEARNING_RATE, hubs=hubs)
    if kind == "dense" and param is not None:
        return DenseNet(seed, lr=param, hubs=hubs)
    raise ValueError(f"unknown learner {kind!r} with parameter {param!r}")


def warm(repo: str) -> tuple[str, ReplayContext, dict[str, Any]]:
    """Labels, boundaries and features of one repository's TRAIN and TEST, from counters."""
    info = REPO[repo]
    recorder = nc.FeatureRecorder(learner("counters", 0, None, info["ctx"].hubs))
    columns: dict[str, Any] = {}
    start = Start.fresh()
    for name in ("train", "test"):
        before = len(recorder.rows)
        done = replay(recorder, info[name], start, ctx=info["ctx"], seed=0)
        start = done.resume()
        columns[name] = {
            "followed": [s.followed for s in done.scores.per_session],
            "boundary": [boundary_steps(s) for s in info[name]],
            "features": np.vstack(recorder.rows[before:]),
            "task_id": [s[0].task_id for s in info[name]],
        }
    return repo, info["ctx"], columns


def traces(columns: dict[str, Any], risks: list[float]) -> tuple[NoteTrace, ...]:
    """Per-session traces from flat risks in replay order."""
    found, start = [], 0
    for task, followed, boundary in zip(
        columns["task_id"], columns["followed"], columns["boundary"], strict=True
    ):
        stop = start + len(followed)
        found.append(NoteTrace(task, tuple(followed), tuple(risks[start:stop]), tuple(boundary)))
        start = stop
    if start != len(risks):
        raise ValueError(f"{len(risks)} risks for {start} steps")
    return tuple(found)


def run_repo(model: Any, repo: str, state: Any) -> dict[str, Any]:
    """TRAIN online then TEST online on one repository, from `state` (None is fresh)."""
    info, out = REPO[repo], {}
    start = Start(History.empty(), state)
    for name in ("train", "test"):
        recorder = RiskRecorder(model)
        done = replay(recorder, info[name], start, ctx=info["ctx"], seed=0)
        start = done.resume()
        out[name] = [float(r) for r in recorder.risks if r is not None]
        out[f"{name}_recall_at_3"] = done.scores.recall_at_3
    return out


def repo_job(job: Job) -> dict[str, Any]:
    """One learner on one held-out repository, starting fresh."""
    kind, seed, param, repo = job
    started = time.time()
    found = run_repo(learner(kind, seed, param, REPO[repo]["ctx"].hubs), repo, None)
    log.info("%s seed %s param %s on %s (%.0fs)", kind, seed, param, repo, time.time() - started)
    return {repo: found}


def pool_job(job: Job) -> dict[str, Any]:
    """One learner trained online through the whole pool, then on each held-out repository."""
    kind, seed, param, _ = job
    started, state = time.time(), None
    pool_learner = learner(kind, seed, param, frozenset())
    for sessions, ctx in rc.REPOS.values():
        state = replay(pool_learner, sessions, Start(History.empty(), state), ctx=ctx, seed=0).state
    found = {
        r: run_repo(learner(kind, seed, param, REPO[r]["ctx"].hubs), r, state) for r in HELD_OUT
    }
    log.info("%s seed %s param %s from the pool (%.0fs)", kind, seed, param, time.time() - started)
    return found


def classifier_job(job: tuple[str, float, str]) -> dict[str, list[float]]:
    """OOF TRAIN risks and full-TRAIN TEST risks of the classifier at one L2 strength."""
    repo, l2, start = job
    train, test = REPO[repo]["columns"]["train"], REPO[repo]["columns"]["test"]
    labels = np.concatenate(train["followed"]).astype(float)
    tasks = sorted(set(train["task_id"]))
    fold_of = dict(zip(tasks, task_folds(len(tasks), sel.SEED), strict=True))
    fold = np.concatenate(
        [
            np.full(len(f), fold_of[t])
            for t, f in zip(train["task_id"], train["followed"], strict=True)
        ]
    )
    pool = pool_steps() if start == "pool" else None
    oof = out_of_fold_risks(Steps(train["features"], labels, fold), l2, always=pool)
    features = train["features"] if pool is None else np.vstack([pool.features, train["features"]])
    fit_labels = labels if pool is None else np.concatenate([pool.labels, labels])
    test_risks = predict(fit_logistic(features, fit_labels, l2), test["features"])
    return {"train": oof.tolist(), "test": test_risks.tolist()}


def pool_steps() -> Steps:
    """Every pool step's features and label (the classifier's warm start)."""
    features = np.vstack([rc.COLUMNS[r]["features"] for r in rc.REPOS])
    labels = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in rc.REPOS]).astype(
        float
    )
    return Steps(features, labels, np.zeros(len(labels)))


def online_jobs() -> list[Job]:
    """Longest first: DenseNet from the pool, then per repository."""
    runs = [("dense", s, lr) for s in sel.WIRING_SEEDS for lr in DENSE_LEARNING_RATES]
    runs += [("mushroom", s, None) for s in sel.WIRING_SEEDS] + [("counters", 0, None)]
    return [(k, s, p, "pool") for k, s, p in runs] + [
        (k, s, p, r) for k, s, p in runs for r in HELD_OUT
    ]


def run_key(kind: str, seed: int) -> tuple[str, int]:
    """Learner row name and seed of one online run."""
    return {"mushroom": "fly"}.get(kind, kind), seed


def collect(jobs: list[Job], found: list[dict[str, Any]], classifier: dict) -> dict:
    """runs[start][learner][seed][repo] = [(TRAIN traces, TEST traces) per block]."""
    runs: dict = {"repo": {}, "pool": {}}
    for (kind, seed, _, where), by_repo in zip(jobs, found, strict=True):
        start = "pool" if where == "pool" else "repo"
        name, run_seed = run_key(kind, seed)
        for repo, out in by_repo.items():
            cols = REPO[repo]["columns"]
            pair = (traces(cols["train"], out["train"]), traces(cols["test"], out["test"]))
            runs[start].setdefault(name, {}).setdefault(run_seed, {}).setdefault(repo, []).append(
                pair
            )
    for (repo, _, start), out in classifier.items():
        cols = REPO[repo]["columns"]
        pair = (traces(cols["train"], out["train"]), traces(cols["test"], out["test"]))
        runs[start].setdefault("logistic", {}).setdefault(0, {}).setdefault(repo, []).append(pair)
    return runs


def recall_record(jobs: list[Job], found: list[dict[str, Any]]) -> dict[str, Any]:
    """TEST recall@3 of every online run that recalls."""
    return {
        f"{k} seed {s} {p} {w} {repo}": out["test_recall_at_3"]
        for (k, s, p, w), by_repo in zip(jobs, found, strict=True)
        for repo, out in by_repo.items()
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """Split, check out hubs, warm features of the held-out repositories and the pool."""
    data_dir, hubs = Path(args.data_dir), {}
    for repo in HELD_OUT:
        parts = split_repo(data_dir, repo, smoke=args.smoke_train_only)
        ctx, hubs[repo] = hub_context(data_dir, repo, parts["train_ids"])
        REPO[repo] = {**parts, "ctx": ctx, "counts": split_counts(parts)}
    for repo, ctx, columns in g6.pool_map(warm, list(HELD_OUT), len(HELD_OUT)):
        REPO[repo]["ctx"], REPO[repo]["columns"] = ctx, columns
    pool = args.pool
    if args.smoke_train_only:
        pool = str(Path(args.out).with_suffix(".smoke-pool.json"))
        whole = json.loads(Path(args.pool).read_text())
        Path(pool).write_text(json.dumps({**whole, "repos": whole["repos"][:3]}))
    rc.prepare(argparse.Namespace(pool=pool, data_dir=args.pool_dir, workers=args.workers))
    return hubs


def run(args: argparse.Namespace) -> None:
    """Replay, fit, apply the registered rules and write the results."""
    started = time.time()
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=PREREG_NAME)
    hubs = prepare(args)
    jobs = online_jobs()
    online = g6.pool_map(online_job, jobs, args.workers)
    fits = [(r, l2, s) for s in ("repo", "pool") for r in HELD_OUT for l2 in L2_GRID]
    classifier = dict(zip(fits, g6.pool_map(classifier_job, fits, args.workers), strict=True))
    body = scored_report(collect(jobs, online, classifier), seed=sel.SEED)
    log.info("verdict: %s", body["verdict"]["live_warner"])
    document = {
        **label,
        "smoke": args.smoke_train_only,
        "code_commit": nc.t36.git_head(),
        "dataset_revision": TRAJECTORIES_REVISION,
        "split_counts": {r: REPO[r]["counts"] for r in HELD_OUT},
        "hub_checkout": hubs,
        "recall_at_3_test": recall_record(jobs, online),
        **body,
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - started)


def online_job(job: Job) -> dict[str, Any]:
    """Dispatch one online job (a module-level function, so forked workers can run it)."""
    return pool_job(job) if job[3] == "pool" else repo_job(job)


def main() -> None:
    """Parse the command line and run one subcommand."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    split_parser = sub.add_parser("split")
    split_parser.add_argument("--data-dir", required=True)
    run_parser = sub.add_parser("run")
    for name in ("data-dir", "pool", "pool-dir", "out"):
        run_parser.add_argument(f"--{name}", required=True)
    run_parser.add_argument("--scored", action="store_true")
    run_parser.add_argument("--prereg")
    run_parser.add_argument("--workers", type=int, default=WORKERS_CAP)
    run_parser.add_argument("--smoke-train-only", action="store_true")
    args = parser.parse_args()
    if args.cmd == "run" and args.scored and args.smoke_train_only:
        parser.error("--smoke-train-only never produces a scored result; drop one of the two")
    if args.cmd == "run" and args.workers > WORKERS_CAP:
        parser.error(f"at most {WORKERS_CAP} workers: half the run host is shared")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    split(args) if args.cmd == "split" else run(args)


if __name__ == "__main__":
    main()
