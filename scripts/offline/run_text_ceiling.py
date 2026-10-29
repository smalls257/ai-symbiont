"""Does the text of each step raise what any learner can predict? The T49 ceiling probe.

prereg/2026-10-28-text-ceiling.md is the rule: pool fold 0 is scored, the other 80 repos train.
Four rows (logistic and T47 MLP on the 86 old features as references, the same plus a 384-dim
step-text embedding under test), hyperparameters chosen inside TRAIN, counters beside every row.
`--rehearsal` scores fold 1 instead and never writes to results/. Parallelism is by process.
Usage: run_text_ceiling.py --pool <pool.json> --embeddings <dir> --out <json> --scored --prereg <md>
"""

import argparse
import json
import logging
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import embed_steps as es
import numpy as np
import run_penalized as t36
import run_repo_curve as rc
import text_ceiling_score as ts

from symbiont.eval import selection as sel
from symbiont.eval.note_cost_logistic import L2_GRID, fit_logistic, predict
from symbiont.eval.note_cost_ranking import roc_auc
from symbiont.eval.prereg_git import run_provenance
from symbiont.eval.tanh_net import NetScorer, fit_mlp

log = logging.getLogger("text-ceiling")
PREREG_NAME = "2026-10-28-text-ceiling.md"
VALID_REPOS = 8  # the tuning slice: the last eight training repositories, as T47's MLP
EMBEDDINGS: dict[str, np.ndarray] = {}
INPUTS = ("old", "old+text")
BAR_RULE = (
    "PASS if MLP old+text minus logistic old is at least +0.03 net value per 100 steps,"
    " paired task-bootstrap 95% lower bound above 0, and ROC AUC rises by at least 0.03"
)


def inputs_of(repo: str, kind: str) -> np.ndarray:
    """The 86 old features of a repository's steps, with the step-text embedding appended."""
    old = rc.COLUMNS[repo]["features"]
    return old if kind == "old" else np.hstack([old, EMBEDDINGS[repo]])


def stack(repos: list[str], kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Inputs and labels of the given repositories, in order."""
    labels = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in repos])
    return np.vstack([inputs_of(r, kind) for r in repos]), labels.astype(bool)


def logistic_job(kind: str) -> dict[str, Any]:
    """Pick the penalty on the tuning slice, refit on every training repository, score."""
    fit_on, tune_on = rc.TRAIN_ORDER[:-VALID_REPOS], rc.TRAIN_ORDER[-VALID_REPOS:]
    (rows, labels), (tune_rows, tune_labels) = stack(fit_on, kind), stack(tune_on, kind)
    tuned = {
        l2: roc_auc(predict(fit_logistic(rows, labels.astype(float), l2), tune_rows), tune_labels)
        for l2 in L2_GRID
    }
    best = max(L2_GRID, key=lambda l2: (tuned[l2], l2))  # ties to the stronger penalty
    rows, labels = stack(rc.TRAIN_ORDER, kind)
    model = fit_logistic(rows, labels.astype(float), best)
    risks = {r: predict(model, inputs_of(r, kind)).tolist() for r in rc.SCORING}
    log.info("logistic %s: penalty %g chosen in TRAIN", kind, best)
    return {"risks": {0: risks}, "chosen": {"l2": best, "tuning_auc": tuned}}


def mlp_job(job: tuple[str, int]) -> dict[str, Any]:
    """T47's MLP (64 tanh units, skip), stopped early on the tuning slice; one wiring seed."""
    kind, seed = job
    fit_on, tune_on = rc.TRAIN_ORDER[:-VALID_REPOS], rc.TRAIN_ORDER[-VALID_REPOS:]
    net, scorer = fit_mlp(stack(fit_on, kind), stack(tune_on, kind), seed), NetScorer()
    risks = {
        r: scorer.step_risks(scorer.encode(inputs_of(r, kind), net), net).tolist()
        for r in rc.SCORING
    }
    log.info("mlp %s seed %d done", kind, seed)
    return {"risks": risks}


def fit_job(job: tuple[str, Any]) -> tuple[tuple[str, Any], dict[str, Any]]:
    """One fit in a forked worker: a logistic row, an MLP seed, or the counters replay."""
    kind, key = job
    if kind == "logistic":
        return job, logistic_job(key)
    if kind == "mlp":
        return job, mlp_job(key)
    return job, {"risks": rc.curve_job(("counters", 0, None, len(rc.TRAIN_ORDER)))}


def fit_all(workers: int) -> dict[str, Any]:
    """Every row's risks per seed, the counters risks and the TRAIN-only choices."""
    jobs: list[tuple[str, Any]] = [("counters", None)]
    jobs += [("mlp", (kind, s)) for kind in INPUTS for s in sel.WIRING_SEEDS]
    jobs += [("logistic", kind) for kind in INPUTS]
    found = dict(fork_map(fit_job, jobs, workers))
    seeds = {f"logistic {kind}": found[("logistic", kind)]["risks"] for kind in INPUTS}
    for kind in INPUTS:
        seeds[f"MLP {kind}"] = {s: found[("mlp", (kind, s))]["risks"] for s in sel.WIRING_SEEDS}
    chosen = {f"logistic {kind}": found[("logistic", kind)]["chosen"] for kind in INPUTS}
    return {"seeds": seeds, "counters": found[("counters", None)]["risks"], "chosen": chosen}


def fork_map(fn: Any, jobs: list[Any], workers: int) -> list[Any]:
    """Map in forked workers; a killed worker raises BrokenProcessPool instead of hanging.

    `multiprocessing.Pool` replaces a worker the system kills (out of memory) and then waits
    forever for its job: the first rehearsal hung that way with nothing in the log.
    """
    context = mp.get_context("fork")
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=context) as pool:
        return list(pool.map(fn, jobs))


def load_embeddings(directory: Path) -> int:
    """Every pool repository's embedding; refuses one whose rows are not its steps."""
    for repo, columns in rc.COLUMNS.items():
        matrix = np.load(es.embedding_path(directory, repo)).astype(np.float64)
        if matrix.shape != (len(columns["features"]), es.DIMS):
            raise ValueError(f"{repo}: embedding {matrix.shape}, {len(columns['features'])} steps")
        EMBEDDINGS[repo] = matrix
    return len(EMBEDDINGS)


def rehearse_on_training_folds(pool: Path) -> None:
    """Score fold 1 and train on folds 2-4, so no metric reads the scoring fold."""
    folds = {e["repo"]: e["fold"] for e in json.loads(pool.read_text())["repos"]}
    rc.SCORING[:] = [r for r in rc.TRAIN_ORDER if folds[r] == 1]
    rc.TRAIN_ORDER[:] = [r for r in rc.TRAIN_ORDER if folds[r] >= 2]


def score_all(fitted: dict[str, Any], workers: int) -> dict[str, Any]:
    """Option A rows, paired gaps, rankings and the verdict under the frozen bar."""
    reference = fitted["seeds"][ts.REFERENCE][0]
    jobs = [(n, s, fitted["counters"], reference) for n, s in fitted["seeds"].items()]
    scored = fork_map(ts.score_row, jobs, workers)
    ranked = {s["name"]: s["ranking"] for s in scored}
    ranked["counters"] = ts.ranks({0: fitted["counters"]})
    auc_gain = ranked[ts.CANDIDATE]["roc_auc"] - ranked[ts.REFERENCE]["roc_auc"]
    rows = _distinct_rows(scored)
    shown = [r for r in rows if r["option"] == ts.HEADLINE]
    return {
        **ts.verdict(ts.headline_gap(scored), auc_gain),
        "headline_option": ts.HEADLINE,
        "table_rows": [ts.table_line(r, ranked[r["arm"]]) for r in shown],
        "rows": rows,
        "differences": [d for s in scored for d in s["differences"]],
        "ranking": ranked,
    }


def _distinct_rows(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each learner's rows in table order, then the counters rows once (every report has them)."""
    learners = [r for s in scored for r in s["rows"] if r["arm"] != "counters"]
    counters = {r["option"]: r for s in scored for r in s["rows"] if r["arm"] == "counters"}
    return learners + list(counters.values())


def run(args: argparse.Namespace) -> None:
    """Guard, load, fit every row in TRAIN, score, apply the bar and write."""
    started = time.time()
    if args.rehearsal and args.scored:
        raise SystemExit("--rehearsal is never a scored run")
    provenance = run_provenance(scored=args.scored, prereg=args.prereg, expects=PREREG_NAME)
    sizes = rc.prepare(
        argparse.Namespace(pool=args.pool, data_dir=args.data_dir, workers=args.workers)
    )
    if args.rehearsal:
        rehearse_on_training_folds(Path(args.pool))
    embedded = load_embeddings(Path(args.embeddings))
    log.info("pool ready %s, %d embedded (%.0fs)", sizes, embedded, time.time() - started)
    fitted = fit_all(args.workers)
    found = score_all(fitted, args.workers)
    document = {
        "verdict": found.pop("verdict"),
        **provenance,
        **_labels(args),
        **sizes,
        "train_repos_used": len(rc.TRAIN_ORDER),
        "scoring_repos_used": len(rc.SCORING),
        "embedding": {"model": es.MODEL, "dims": es.DIMS},
        "roles": ts.ROLES | {"counters": "reference"},
        "chosen_in_train": fitted["chosen"],
        "rule": BAR_RULE,
        **found,
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_verdict_first(Path(args.out), document)
    for line in document["table_rows"]:
        log.info(line)
    log.info(
        "wrote %s: %s (wall clock %.0fs)", args.out, document["verdict"], time.time() - started
    )


def _labels(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "task": "T49",
        "asks": "does a step-text embedding raise what any learner can predict",
        "data_label": "gate on re-used data, not a scored claim",
        "data_note": "the 20 pool scoring repositories were already used in exploratory work",
        "rehearsal": bool(args.rehearsal),
        "code_commit": t36.git_head(),
        "pool": args.pool,
    }


def write_verdict_first(path: Path, document: dict[str, Any]) -> None:
    """JSON whose first line carries the verdict word, as the prereg asks."""
    rest = {k: v for k, v in document.items() if k != "verdict"}
    body = json.dumps(rest, indent=1)
    path.write_text(f'{{"verdict": {json.dumps(document["verdict"])},\n' + body[2:] + "\n")


def main() -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("pool", "data-dir", "embeddings", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--scored", action="store_true")
    parser.add_argument("--prereg")
    parser.add_argument("--rehearsal", action="store_true")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
