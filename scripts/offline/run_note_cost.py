"""How a note earns the right to speak (T46): exploratory, TRAIN split only. Periphery script.

`features` stores the per-step features the learners saw over TRAIN, for the batch
classifier row. `trace` replays the T36 TRAIN sessions online (same split, order, hub,
labels and learning cost as T36) and stores each learner's risk, label and boundary
mark per step under data/.
No TEST session is replayed or scored. `score` reads those traces and writes the
task-grouped cross-validation over TRAIN (`symbiont.eval.note_cost_report`).

    run_note_cost.py trace --data data/nebius-openhands/sqlglot.jsonl \
        --meta data/nebius-openhands/sqlglot_meta.json --out data/note-cost-traces.json
    run_note_cost.py features --data ... --meta ... --out data/note-cost-features.npy
    run_note_cost.py score --traces data/note-cost-traces.json \
        --features data/note-cost-features.npy --out results/note-cost-exploratory.json

Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1: parallelism is by process.
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
import run_penalized as t36
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.net_benefit import DENSE_LEARNING_RATES, PRIMARY_COST
from symbiont.eval.note_cost_logistic import L2_GRID, outer_fold_risks
from symbiont.eval.note_cost_report import Arms, report
from symbiont.eval.note_cost_select import FOLDS, task_folds
from symbiont.eval.note_delivery import NoteTrace, boundary_steps
from symbiont.eval.offline import Start, replay
from symbiont.eval.warning_budget_metrics import RiskRecorder, risk_traces

log = logging.getLogger("note-cost")
Job = tuple[str, int, float | None]


def train_risks(job: Job) -> list[float]:
    """Replay TRAIN online for one learner and return every step's risk in replay order."""
    kind, seed, param = job
    started = time.time()
    recorder = RiskRecorder(t36.make_learner(kind, seed, param))
    done = replay(recorder, g6.TRAIN, Start.fresh(), ctx=g6.CTX, seed=g6.REPLAY_SEED)
    traces = risk_traces(done.scores, recorder)
    risks = [r for trace in traces for r in trace.risk]
    if any(r is None for r in risks):
        raise ValueError(f"{kind} seed {seed} reported a step with no risk score")
    log.info("traced %s seed=%s param=%s (%.0fs)", kind, seed, param, time.time() - started)
    return [float(r) for r in risks if r is not None]


def job_key(job: Job) -> str:
    """A short label for one replay, as the traces file names it."""
    kind, seed, param = job
    return f"{kind} seed {seed}" + (f" lr {param:g}" if param is not None else "")


def session_columns() -> dict[str, Any]:
    """Task id, labels and boundary marks per TRAIN session, shared by every learner."""
    counters = t36.make_learner("counters", 0, None)
    scores = replay(counters, g6.TRAIN, Start.fresh(), ctx=g6.CTX, seed=g6.REPLAY_SEED).scores
    sessions = list(zip(g6.TRAIN, scores.per_session, strict=True))
    return {
        "task_id": [scored.task_id for _, scored in sessions],
        "followed": ["".join("1" if f else "0" for f in s.followed) for _, s in sessions],
        "boundary": [
            "".join("1" if b else "0" for b in boundary_steps(rec)) for rec, _ in sessions
        ],
    }


def trace(args: argparse.Namespace) -> None:
    """Replay every learner over TRAIN and store the traces (never TEST)."""
    started = time.time()
    meta = json.loads(Path(args.meta).read_text())
    g6.TRAIN, _, train_ids, _, counts = g6.prepare_sessions(Path(args.data), smoke=args.smoke)
    g6.TEST = []
    hub = g6.prepare_hubs(meta, train_ids)
    g6.CTX.false_alarm_cost = PRIMARY_COST
    columns = session_columns()  # also fills the feature cache the forked workers inherit
    log.info("session columns ready (%.0fs)", time.time() - started)
    jobs: list[Job] = [("counters", 0, None)]
    jobs += [("mushroom", s, None) for s in sel.WIRING_SEEDS]
    jobs += [("dense", s, lr) for s in sel.WIRING_SEEDS for lr in DENSE_LEARNING_RATES]
    risks = dict(zip(map(job_key, jobs), g6.pool_map(train_risks, jobs, args.workers), strict=True))
    document = {
        "split": "train",
        "smoke": args.smoke,
        "code_commit": t36.git_head(),
        "learning_false_alarm_cost": PRIMARY_COST,
        "data": {**counts, "tasks_train": len(train_ids), "sessions_train": len(g6.TRAIN)},
        "hub_task": hub.task_id,
        "sessions": columns,
        "risk": risks,
        "wall_clock_s": time.time() - started,
    }
    Path(args.out).write_text(json.dumps(document))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - started)


class FeatureRecorder:
    """Wraps a learner for a replay and keeps the feature vector of every decided step."""

    def __init__(self, inner: Any) -> None:
        """Wrap `inner`; it decides and learns as usual."""
        self._inner = inner
        self.name = inner.name
        self.rows: list[np.ndarray] = []

    def initial_state(self, seed: int) -> Any:
        """The wrapped learner's fresh state."""
        return self._inner.initial_state(seed)

    def decide(self, x: np.ndarray, situation: Any, state: Any) -> Any:
        """Note the features, then decide as the wrapped learner does."""
        self.rows.append(np.array(x, dtype=np.float64))
        return self._inner.decide(x, situation, state)

    def learn(self, x: np.ndarray, outcome: Any, state: Any) -> Any:
        """Learn as the wrapped learner does."""
        return self._inner.learn(x, outcome, state)


def features(args: argparse.Namespace) -> None:
    """Store the per-step features the learners saw over TRAIN, in replay order (never TEST)."""
    meta = json.loads(Path(args.meta).read_text())
    g6.TRAIN, _, train_ids, _, _ = g6.prepare_sessions(Path(args.data), smoke=args.smoke)
    g6.TEST = []
    g6.prepare_hubs(meta, train_ids)
    g6.CTX.false_alarm_cost = PRIMARY_COST
    recorder = FeatureRecorder(t36.make_learner("counters", 0, None))
    replay(recorder, g6.TRAIN, Start.fresh(), ctx=g6.CTX, seed=g6.REPLAY_SEED)
    matrix = np.vstack(recorder.rows)
    np.save(args.out, matrix)
    log.info("wrote %s: %d steps x %d features", args.out, *matrix.shape)


FEATURES: np.ndarray = np.empty((0, 0))
LABELS: np.ndarray = np.empty(0)
STEP_FOLD: np.ndarray = np.empty(0)


def classifier_job(job: tuple[int, float]) -> list[float]:
    """Out-of-sample classifier risks for one (outer fold, L2 strength)."""
    outer, l2 = job
    started = time.time()
    risks = outer_fold_risks(FEATURES, LABELS, STEP_FOLD, outer, l2)
    log.info("classifier fold %d l2 %g (%.0fs)", outer, l2, time.time() - started)
    return risks.tolist()


def classifier_traces(document: dict[str, Any], path: str, workers: int) -> dict:
    """Fit the batch classifier per outer fold and L2 strength, in forked workers."""
    global FEATURES, LABELS, STEP_FOLD
    columns = document["sessions"]
    FEATURES = np.load(path)
    LABELS = np.array([f == "1" for row in columns["followed"] for f in row], dtype=np.float64)
    if len(FEATURES) != len(LABELS):
        raise ValueError(f"{len(FEATURES)} feature rows for {len(LABELS)} TRAIN steps")
    tasks = sorted(set(columns["task_id"]))
    fold_of = dict(zip(tasks, task_folds(len(tasks), sel.SEED), strict=True))
    STEP_FOLD = np.concatenate(
        [
            np.full(len(f), fold_of[t])
            for t, f in zip(columns["task_id"], columns["followed"], strict=True)
        ]
    )
    jobs = [(outer, l2) for outer in range(FOLDS) for l2 in L2_GRID]
    risks = dict(zip(jobs, g6.pool_map(classifier_job, jobs, workers), strict=True))
    return {
        outer: {
            l2: cut_traces(document, risks[(outer, l2)], f"classifier {outer}") for l2 in L2_GRID
        }
        for outer in range(FOLDS)
    }


def note_traces(document: dict[str, Any], key: str) -> tuple[NoteTrace, ...]:
    """Cut one learner's flat risks back into per-session traces."""
    return cut_traces(document, document["risk"][key], key)


def cut_traces(document: dict[str, Any], risks: list[float], key: str) -> tuple[NoteTrace, ...]:
    """Per-session traces from flat per-step risks in replay order."""
    columns, start, traces = document["sessions"], 0, []
    rows = zip(*(columns[k] for k in ("task_id", "followed", "boundary")), strict=True)
    for task, followed, boundary in rows:
        stop = start + len(followed)
        traces.append(
            NoteTrace(
                task,
                tuple(f == "1" for f in followed),
                tuple(risks[start:stop]),
                tuple(b == "1" for b in boundary),
            )
        )
        start = stop
    if start != len(risks):
        raise ValueError(f"{key}: {len(risks)} risks for {start} steps")
    return tuple(traces)


def score(args: argparse.Namespace) -> None:
    """Cross-validate every option over the TRAIN traces and write the results file."""
    document = json.loads(Path(args.traces).read_text())
    if document["split"] != "train":
        raise ValueError("note-cost traces must come from the TRAIN split only")
    arms = Arms(
        counters=note_traces(document, "counters seed 0"),
        fly={s: note_traces(document, f"mushroom seed {s}") for s in sel.WIRING_SEEDS},
        dense={
            s: {
                lr: note_traces(document, f"dense seed {s} lr {lr:g}")
                for lr in DENSE_LEARNING_RATES
            }
            for s in sel.WIRING_SEEDS
        },
        logistic=classifier_traces(document, args.features, args.workers)
        if args.features
        else None,
    )
    body = report(arms, seed=sel.SEED)
    for line in body["table_rows"]:
        log.info(line)
    out = {
        "run_label": "exploratory",
        "split": "train, task-grouped cross-validation; the T36 test split is not read",
        "smoke": document["smoke"],
        "trace_code_commit": document["code_commit"],
        "score_code_commit": t36.git_head(),
        "learning_false_alarm_cost": document["learning_false_alarm_cost"],
        "data": {**document["data"], "split_seed": sel.SEED, "test_fraction": sel.TEST_FRACTION},
        "hub_task": document["hub_task"],
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **body,
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    log.info("wrote %s", args.out)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one subcommand."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    trace_parser = sub.add_parser("trace")
    for name in ("data", "meta", "out"):
        trace_parser.add_argument(f"--{name}", required=True)
    trace_parser.add_argument("--workers", type=int, default=13)
    trace_parser.add_argument("--smoke", action="store_true")
    score_parser = sub.add_parser("score")
    for name in ("traces", "out"):
        score_parser.add_argument(f"--{name}", required=True)
    score_parser.add_argument("--features")
    score_parser.add_argument("--workers", type=int, default=13)
    features_parser = sub.add_parser("features")
    for name in ("data", "meta", "out"):
        features_parser.add_argument(f"--{name}", required=True)
    features_parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    {"trace": trace, "score": score, "features": features}[args.cmd](args)


if __name__ == "__main__":
    main()
