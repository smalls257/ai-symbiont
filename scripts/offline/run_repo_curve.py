"""Is it data variety? A learning curve over the number of training repositories (T46).

Exploratory, on the pool of `results/repo-pool.json` only (no held-out, no sqlglot row).
Pool fold 0 is scored; the other folds train, in pool order, the first N of them. Each
learner replays its N training repositories online one after another, carrying its state
(each repository with its own history, as the product works per project), then replays each
scoring repository online from that state. The batch classifier is fit on the same N
repositories' features. Every row is scored under option A by cross-validation grouped by
scoring repository (`symbiont.eval.note_cost_report`, a repository standing in for a task).

    run_repo_curve.py --pool results/repo-pool.json --data-dir data/nebius-openhands/pool \
        --dense-rate 0.1 --l2 100 --out results/note-cost-repo-curve.json

Labels in the pool carry no blast-radius signal and no hub filter: no repository checkout is
made. Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1: parallelism is by process.
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import run_note_cost as nc
import run_penalized as t36
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_cost_logistic import fit_logistic, predict
from symbiont.eval.note_cost_ranking import ranking
from symbiont.eval.note_cost_report import Arms, report
from symbiont.eval.note_cost_select import FOLDS, PRIMARY
from symbiont.eval.note_delivery import NoteTrace, boundary_steps
from symbiont.eval.offline import History, ReplayContext, Start, drop_taskless, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder
from symbiont.readers import openhands

log = logging.getLogger("repo-curve")
N_GRID = (1, 10, 50, 80)  # training repositories; 80 is every non-scoring pool repository
SCORING_FOLD = 0
KEPT_OPTIONS = ("a_heads_up_gain_1", PRIMARY)
REPOS: dict[str, tuple[list, ReplayContext]] = {}
COLUMNS: dict[str, dict[str, Any]] = {}
TRAIN_ORDER: list[str] = []
SCORING: list[str] = []


def load_repo(path: Path, repo: str) -> list:
    """Sessions of one repository in the seeded replay order."""
    sessions, _ = drop_taskless(sel.group_sessions(list(openhands.read(path, repo))))
    return list(sel.replay_order(sessions))


def warm(repo: str) -> tuple[str, ReplayContext, dict[str, Any]]:
    """Labels, boundaries and features of one repository, from one counters pass."""
    sessions, ctx = REPOS[repo]
    recorder = nc.FeatureRecorder(t36.make_learner("counters", 0, None))
    scores = replay(recorder, sessions, Start.fresh(), ctx=ctx, seed=g6.REPLAY_SEED).scores
    columns = {
        "followed": [s.followed for s in scores.per_session],
        "boundary": [boundary_steps(s) for s in sessions],
        "features": np.vstack(recorder.rows),
    }
    return repo, ctx, columns


def curve_job(job: tuple[str, int, float | None, int]) -> dict[str, list[float]]:
    """Train on the first N repositories, then record risks on every scoring repository."""
    kind, seed, param, n_repos = job
    started, learner, state = time.time(), t36.make_learner(kind, seed, param), None
    for repo in TRAIN_ORDER[:n_repos]:
        sessions, ctx = REPOS[repo]
        state = replay(learner, sessions, Start(History.empty(), state), ctx=ctx, seed=0).state
    risks = {}
    for repo in SCORING:
        sessions, ctx = REPOS[repo]
        recorder = RiskRecorder(learner)
        replay(recorder, sessions, Start(History.empty(), state), ctx=ctx, seed=0)
        risks[repo] = [float(r) for r in recorder.risks if r is not None]
    log.info("%s seed %s n=%d (%.0fs)", kind, seed, n_repos, time.time() - started)
    return risks


def traces_of(risks: dict[str, list[float]]) -> tuple[NoteTrace, ...]:
    """Per-session traces of the scoring repositories; the repository is the group."""
    traces = []
    for repo in SCORING:
        flat, start = risks[repo], 0
        for followed, boundary in zip(
            COLUMNS[repo]["followed"], COLUMNS[repo]["boundary"], strict=True
        ):
            stop = start + len(followed)
            traces.append(
                NoteTrace(repo, tuple(followed), tuple(flat[start:stop]), tuple(boundary))
            )
            start = stop
        if start != len(flat):
            raise ValueError(f"{repo}: {len(flat)} risks for {start} steps")
    return tuple(traces)


def classifier_risks(n_repos: int, l2: float) -> dict[str, list[float]]:
    """Batch classifier fit on the first N training repositories' features."""
    train = TRAIN_ORDER[:n_repos]
    features = np.vstack([COLUMNS[r]["features"] for r in train])
    labels = np.concatenate([np.concatenate(COLUMNS[r]["followed"]) for r in train]).astype(float)
    model = fit_logistic(features, labels, l2)
    return {r: predict(model, COLUMNS[r]["features"]).tolist() for r in SCORING}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """Load the pool, fix the order and warm every repository's labels and features."""
    pool = json.loads(Path(args.pool).read_text())
    for entry in pool["repos"]:
        path = Path(args.data_dir) / (entry["repo"].replace("/", "__") + ".jsonl")
        ctx = ReplayContext(references={}, hubs=frozenset(), false_alarm_cost=PRIMARY_COST)
        REPOS[entry["repo"]] = (load_repo(path, entry["repo"]), ctx)
    TRAIN_ORDER[:] = [e["repo"] for e in pool["repos"] if e["fold"] != SCORING_FOLD]
    SCORING[:] = [e["repo"] for e in pool["repos"] if e["fold"] == SCORING_FOLD]
    for repo, ctx, columns in g6.pool_map(warm, list(REPOS), args.workers):
        REPOS[repo] = (REPOS[repo][0], ctx)
        COLUMNS[repo] = columns
    steps = {r: int(sum(map(len, COLUMNS[r]["followed"]))) for r in REPOS}
    return {
        "pool_repos": len(REPOS),
        "train_repos": len(TRAIN_ORDER),
        "scoring_repos": len(SCORING),
        "sessions": sum(len(REPOS[r][0]) for r in REPOS),
        "steps_train_pool": sum(steps[r] for r in TRAIN_ORDER),
        "steps_scoring": sum(steps[r] for r in SCORING),
    }


def arms_at(n_repos: int, risks: dict, args: argparse.Namespace) -> Arms:
    """Scoring traces of every learner trained on the first N repositories."""
    seeds, rate = sel.WIRING_SEEDS, args.dense_rate
    classifier = traces_of(risks[("logistic", 0, args.l2, n_repos)])
    return Arms(
        counters=traces_of(risks[("counters", 0, None, n_repos)]),
        fly={s: traces_of(risks[("mushroom", s, None, n_repos)]) for s in seeds},
        dense={s: {rate: traces_of(risks[("dense", s, rate, n_repos)])} for s in seeds},
        logistic={fold: {args.l2: classifier} for fold in range(FOLDS)},
    )


def ranking_at(n_repos: int, risks: dict) -> dict[str, Any]:
    """Threshold-free ranking of each run on the scoring repositories."""
    followed = np.concatenate([np.concatenate(COLUMNS[r]["followed"]) for r in SCORING])
    found = {}
    for key, by_repo in risks.items():
        if key[3] == n_repos:
            flat = np.concatenate([by_repo[r] for r in SCORING])
            found[f"{key[0]} seed {key[1]}"] = ranking(flat, followed)
    return found


def curve_point(n_repos: int, risks: dict, args: argparse.Namespace) -> dict[str, Any]:
    """Option A rows, differences and ranking at one N."""
    body = report(arms_at(n_repos, risks, args), seed=sel.SEED)

    def kept(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**i, "train_repos": n_repos} for i in items if i["option"] in KEPT_OPTIONS]

    lines = [line for line in body["table_rows"] if line.split(" |")[0] in KEPT_OPTIONS]
    return {
        "rows": kept(body["rows"]),
        "differences": kept(body["differences"]),
        "ranking": ranking_at(n_repos, risks),
        "table_rows": [f"n={n_repos} | {line}" for line in lines],
    }


def curve_jobs(args: argparse.Namespace) -> list[tuple[str, int, float | None, int]]:
    """Longest jobs first: DenseNet on the most repositories."""
    largest_first = sorted(N_GRID, reverse=True)
    jobs: list[tuple[str, int, float | None, int]] = []
    for kind, rate in (("dense", args.dense_rate), ("mushroom", None)):
        jobs += [(kind, s, rate, n) for n in largest_first for s in sel.WIRING_SEEDS]
    return jobs + [("counters", 0, None, n) for n in N_GRID]


def run(args: argparse.Namespace) -> None:
    """Warm, train and score every N, then write the curve."""
    started = time.time()
    sizes = prepare(args)
    log.info("pool ready %s (%.0fs)", sizes, time.time() - started)
    jobs = curve_jobs(args)
    risks = dict(zip(jobs, g6.pool_map(curve_job, jobs, args.workers), strict=True))
    risks.update({("logistic", 0, args.l2, n): classifier_risks(n, args.l2) for n in N_GRID})
    points = [curve_point(n, risks, args) for n in N_GRID]
    document = {
        "run_label": "exploratory",
        "asks": "is it data variety: option A value by number of training repos",
        "code_commit": t36.git_head(),
        "pool": args.pool,
        **sizes,
        "n_grid": list(N_GRID),
        "dense_rate": args.dense_rate,
        "classifier_l2": args.l2,
        "labels_note": "no blast-radius signal and no hub filter in the pool (no checkout)",
        "rows": [r for p in points for r in p["rows"]],
        "differences": [d for p in points for d in p["differences"]],
        "ranking": {str(n): p["ranking"] for n, p in zip(N_GRID, points, strict=True)},
        "table_rows": [line for p in points for line in p["table_rows"]],
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    for line in document["table_rows"]:
        log.info(line)
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - started)


def main() -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("pool", "data-dir", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--dense-rate", type=float, required=True)
    parser.add_argument("--l2", type=float, required=True)
    parser.add_argument("--workers", type=int, default=13)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
