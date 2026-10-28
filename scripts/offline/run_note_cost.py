"""How a note earns the right to speak (T46): exploratory, TRAIN split only. Periphery script.

`features` stores the per-step features over TRAIN; `trace` replays the T36 TRAIN sessions online
and stores each learner's risk, label and boundary mark per step under data/; `score` reads them
and writes the task-grouped cross-validation (`symbiont.eval.note_cost_report`). No TEST session
is used. Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1.
Usage: run_note_cost.py {trace|features|score} --data ... --meta ... --out ...
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
from symbiont.eval.note_cost_logistic import L2_GRID, Steps, outer_fold_risks
from symbiont.eval.note_cost_ranking import ranking
from symbiont.eval.note_cost_report import NESTED, Arms, report
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
STEP_TASK: np.ndarray = np.empty(0)
TASK_FOLD: np.ndarray = np.empty(0)
DOCUMENT: dict[str, Any] = {}
FRACTIONS = (0.25, 0.5, 1.0)  # share of each outer fold's training tasks the classifier fits on
FRACTION_SEEDS = (0, 1, 2)
FRACTION_L2 = 1000.0  # the strength picked most often on TRAIN folds under option A
CURVE_OPTIONS = ("a_heads_up_gain_1", "a_tiers_boundary_budget")


def load_classifier_inputs(document: dict[str, Any], path: str) -> None:
    """Features, labels, and the task and fold of every TRAIN step, for forked workers."""
    global FEATURES, LABELS, STEP_FOLD, STEP_TASK, TASK_FOLD, DOCUMENT
    columns, DOCUMENT = document["sessions"], document
    FEATURES = np.load(path)
    LABELS = np.array([f == "1" for row in columns["followed"] for f in row], dtype=np.float64)
    if len(FEATURES) != len(LABELS):
        raise ValueError(f"{len(FEATURES)} feature rows for {len(LABELS)} TRAIN steps")
    tasks = sorted(set(columns["task_id"]))
    index = {task: i for i, task in enumerate(tasks)}
    TASK_FOLD = task_folds(len(tasks), sel.SEED)
    pairs = zip(columns["task_id"], columns["followed"], strict=True)
    STEP_TASK = np.concatenate([np.full(len(f), index[t]) for t, f in pairs])
    STEP_FOLD = TASK_FOLD[STEP_TASK]


def classifier_job(job: tuple[int, float]) -> list[float]:
    """Out-of-sample classifier risks for one (outer fold, L2 strength)."""
    outer, l2 = job
    started = time.time()
    risks = outer_fold_risks(Steps(FEATURES, LABELS, STEP_FOLD), outer, l2)
    log.info("classifier fold %d l2 %g (%.0fs)", outer, l2, time.time() - started)
    return risks.tolist()


def classifier_risks(document: dict[str, Any], path: str, workers: int) -> dict:
    """Fit the batch classifier per outer fold and L2 strength, in forked workers."""
    load_classifier_inputs(document, path)
    jobs = [(outer, l2) for outer in range(FOLDS) for l2 in L2_GRID]
    return dict(zip(jobs, g6.pool_map(classifier_job, jobs, workers), strict=True))


def pooled_held_out(by_outer: dict[int, list[float]]) -> np.ndarray:
    """Each step's risk from the model of its own outer fold."""
    pooled = np.empty(len(LABELS))
    for outer, risks in by_outer.items():
        held = outer == STEP_FOLD
        pooled[held] = np.asarray(risks)[held]
    return pooled


def classifier_ranking(risks: dict) -> dict[str, Any]:
    """Held-out ranking of the classifier per L2 strength."""
    return {
        f"l2 {l2:g}": ranking(
            pooled_held_out({o: risks[(o, l2)] for o in range(FOLDS)}), LABELS.astype(bool)
        )
        for l2 in L2_GRID
    }


def fraction_job(job: tuple[float, int]) -> dict[str, Any]:
    """The classifier fit on a sampled share of each outer fold's training tasks, scored."""
    fraction, seed = job
    rng, by_outer = np.random.default_rng(seed), {}
    for outer in range(FOLDS):
        candidates = np.flatnonzero(outer != TASK_FOLD)
        keep = rng.choice(candidates, size=max(1, round(fraction * len(candidates))), replace=False)
        mask = np.isin(STEP_TASK, keep)
        risks = outer_fold_risks(Steps(FEATURES, LABELS, STEP_FOLD), outer, FRACTION_L2, mask)
        by_outer[outer] = risks.tolist()
    traces = {o: {FRACTION_L2: cut_traces(DOCUMENT, r, f"fold {o}")} for o, r in by_outer.items()}
    arms = arms_of(DOCUMENT, None)
    body = report(Arms(arms.counters, arms.fly, arms.dense, logistic=traces), seed=sel.SEED)
    rows = [
        {**r, "train_task_share": fraction, "sample_seed": seed}
        for r in body["rows"]
        if r["arm"] == NESTED and r["option"] in CURVE_OPTIONS
    ]
    log.info("classifier fraction %g seed %d done", fraction, seed)
    return {"rows": rows, "ranking": ranking(pooled_held_out(by_outer), LABELS.astype(bool))}


def fractions(args: argparse.Namespace) -> None:
    """Classifier learning curve over the share of TRAIN tasks it fits on (TRAIN only)."""
    document = json.loads(Path(args.traces).read_text())
    if document["split"] != "train":
        raise ValueError("note-cost traces must come from the TRAIN split only")
    load_classifier_inputs(document, args.features)
    jobs = [(f, s) for f in FRACTIONS for s in FRACTION_SEEDS]
    done = g6.pool_map(fraction_job, jobs, args.workers)
    out = {
        "run_label": "exploratory",
        "asks": "does the batch classifier still improve with more TRAIN tasks",
        "code_commit": t36.git_head(),
        "l2": FRACTION_L2,
        "fractions": list(FRACTIONS),
        "sample_seeds": list(FRACTION_SEEDS),
        "rows": [r for d in done for r in d["rows"]],
        "ranking": [
            {"train_task_share": f, "sample_seed": s, **d["ranking"]}
            for (f, s), d in zip(jobs, done, strict=True)
        ],
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    log.info("wrote %s", args.out)


def online_ranking(document: dict[str, Any]) -> dict[str, Any]:
    """Ranking of each online learner's prequential TRAIN risks."""
    followed = np.array([f == "1" for row in document["sessions"]["followed"] for f in row])
    return {key: ranking(np.asarray(r), followed) for key, r in document["risk"].items()}


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


def arms_of(document: dict[str, Any], risks: dict | None) -> Arms:
    """Every learner's TRAIN traces; the classifier's per outer fold and L2 strength."""
    classifier = None
    if risks is not None:
        classifier = {
            outer: {l2: cut_traces(document, risks[(outer, l2)], f"fold {outer}") for l2 in L2_GRID}
            for outer in range(FOLDS)
        }
    rates = DENSE_LEARNING_RATES
    return Arms(
        counters=note_traces(document, "counters seed 0"),
        fly={s: note_traces(document, f"mushroom seed {s}") for s in sel.WIRING_SEEDS},
        dense={
            s: {lr: note_traces(document, f"dense seed {s} lr {lr:g}") for lr in rates}
            for s in sel.WIRING_SEEDS
        },
        logistic=classifier,
    )


def score(args: argparse.Namespace) -> None:
    """Cross-validate every option over the TRAIN traces and write the results file."""
    document = json.loads(Path(args.traces).read_text())
    if document["split"] != "train":
        raise ValueError("note-cost traces must come from the TRAIN split only")
    risks = classifier_risks(document, args.features, args.workers) if args.features else None
    body = report(arms_of(document, risks), seed=sel.SEED)
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
        "ranking": {
            "online_prequential": online_ranking(document),
            "classifier_held_out": None if risks is None else classifier_ranking(risks),
        },
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
    fractions_parser = sub.add_parser("fractions")
    for name in ("traces", "features", "out"):
        fractions_parser.add_argument(f"--{name}", required=True)
    fractions_parser.add_argument("--workers", type=int, default=9)
    features_parser = sub.add_parser("features")
    for name in ("data", "meta", "out"):
        features_parser.add_argument(f"--{name}", required=True)
    features_parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    {"trace": trace, "score": score, "features": features, "fractions": fractions}[args.cmd](args)


if __name__ == "__main__":
    main()
