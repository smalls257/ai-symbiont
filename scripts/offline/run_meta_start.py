"""Meta-train where the fly and DenseNet start, then score every row (T39). Periphery script.

`train` meta-trains each filler's readout start and calibrator on the pool's training
repositories, one job per (filler, wiring seed, outer step size), stopping on the
validation repositories (`symbiont.eval.meta_start`). `score` replays every row online from
zero on each evaluation repository and writes option A rows per window
(`symbiont.eval.meta_start_report`). The scoring fold is only read with `--scored` and a
frozen prereg; the smoke run scores the validation repositories, labeled exploratory.

    meta_start_episodes.py ...                  # once: data/t39-episodes.npz
    run_meta_start.py train --episodes data/t39-episodes.npz --pool results/repo-pool.json \
        --out data/t39-starts.npz
    run_meta_start.py score --episodes ... --pool ... --starts data/t39-starts.npz \
        --on validation --out results/meta-start-smoke.json
    run_meta_start.py score ... --on scoring --scored --prereg prereg/2026-10-28-meta-start.md

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

import meta_start_episodes as eps
import numpy as np
import run_penalized as t36
import run_selection as g6

from symbiont.core.dense import DenseNet
from symbiont.core.meta import MetaLearnable
from symbiont.core.mushroom import Mushroom
from symbiont.eval import selection as sel
from symbiont.eval.meta_start import (
    MetaConfig,
    MetaRule,
    MetaSplit,
    calibrated_risks,
    cold_start,
    meta_split,
    meta_train,
    online_risks,
)
from symbiont.eval.meta_start_report import (
    ADAPTING_CLASSIFIER,
    CLASSIFIER,
    COUNTERS,
    meta_report,
    note_traces,
)
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_cost_logistic import fit_logistic, predict
from symbiont.eval.prereg_git import run_provenance

log = logging.getLogger("t39")
PREREG_NAME = "2026-10-28-meta-start.md"
DENSE_RATE = 0.1  # T46 ruling 13: the DenseNet rate TRAIN-CV picked most
CLASSIFIER_L2 = 1000.0  # T46 ruling 13: the classifier strength TRAIN-CV picked most
# Outer step sizes per rule, chosen with the rule on the validation repositories: Adam
# steps for first-order MAML, the fraction of the way toward the adapted start for Reptile.
OUTER_GRID = {
    MetaRule.FIRST_ORDER_MAML: (0.001, 0.003, 0.01),
    MetaRule.REPTILE: (0.03, 0.1, 0.3),
}
FILLERS = ("fly", "dense")
DATA: dict[str, eps.RepoSteps] = {}
SPLIT: list[MetaSplit] = []
SETTINGS: dict[str, Any] = {}


def filler_of(kind: str, seed: int) -> MetaLearnable:
    """The fly (T36 rate) or DenseNet (T46 rate) with this wiring seed."""
    if kind == "fly":
        return Mushroom(seed, lr=sel.LEARNING_RATE)
    if kind == "dense":
        return DenseNet(seed, lr=DENSE_RATE)
    raise ValueError(f"unknown filler {kind!r}")


def train_job(job: tuple[str, int, MetaRule, float]) -> dict[str, Any]:
    """Meta-train one filler under one rule and step size; the start and its curve."""
    kind, seed, rule, rate = job
    started, split = time.time(), SPLIT[0]
    train = [DATA[r].episode for r in split.train[: SETTINGS["train_repos"]]]
    validation = [DATA[r].episode for r in split.validation]
    config = MetaConfig(rate, rule, outer_steps=SETTINGS["outer_steps"], seed=seed)
    result = meta_train(filler_of(kind, seed), train, validation, config)
    seconds = time.time() - started
    log.info(
        "%s seed %d %s %g: best step %d loss %.4f (cold %.4f) %.0fs",
        *(kind, seed, rule, rate, result.best_step, result.best_loss, result.curve[0][1], seconds),
    )
    return {
        "kind": kind,
        "seed": seed,
        "rule": rule.name,
        "outer_rate": rate,
        "best_step": result.best_step,
        "curve": [list(c) for c in result.curve],
        "start": result.start.as_vector(),
        "seconds": seconds,
    }


def train(args: argparse.Namespace) -> None:
    """Every (filler, seed, outer step size) job; starts to npz, curves to json, both data/."""
    prepare(args)
    SETTINGS.update(train_repos=args.train_repos, outer_steps=args.outer_steps)
    grid = [(rule, rate) for rule, rates in OUTER_GRID.items() for rate in rates]
    jobs = [(k, s, *g) for k in FILLERS for s in args.seeds for g in grid]
    jobs.sort(key=lambda job: job[0] != "fly")  # the fly's jobs are the long ones
    done = g6.pool_map(train_job, jobs, args.workers)
    starts = {
        start_key(d["kind"], d["seed"], d["rule"], d["outer_rate"]): d.pop("start") for d in done
    }
    np.savez(args.out, **starts)
    summary = {"code_commit": t36.git_head(), **SETTINGS, "jobs": done}
    Path(args.out).with_suffix(".json").write_text(json.dumps(summary, indent=1))
    log.info("wrote %s", args.out)


def start_key(kind: str, seed: int, rule: str, rate: float) -> str:
    """The name of one trained start in the starts file."""
    return f"{kind}.{seed}.{rule}.{rate:g}"


def prepare(args: argparse.Namespace) -> None:
    """Load the episodes and fix the split; the forked workers inherit both."""
    pool = json.loads(Path(args.pool).read_text())["repos"]
    SPLIT[:] = [meta_split(pool)]
    DATA.update(eps.load(args.episodes))


def best_starts(path: str) -> dict[tuple[str, int], dict[str, Any]]:
    """Per (filler, seed): the rule and step size with the lowest validation loss."""
    jobs = json.loads(Path(path).with_suffix(".json").read_text())["jobs"]
    best: dict[tuple[str, int], dict[str, Any]] = {}
    for job in jobs:
        loss = min(point[1] for point in job["curve"])
        key = (job["kind"], job["seed"])
        if key not in best or loss < best[key]["validation_loss"]:
            best[key] = {
                "rule": job["rule"],
                "outer_rate": job["outer_rate"],
                "best_step": job["best_step"],
                "validation_loss": loss,
                "cold_validation_loss": job["curve"][0][1],
            }
    return best


def evaluation_repos(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, list[str]]:
    """Which repositories are scored and which the classifier fits on.

    The scoring fold is read only in a scored run; a smoke run scores validation and fits
    the classifier on the same training repositories the starts saw.
    """
    split = SPLIT[0]
    if args.on == "scoring":
        return {"scored": list(split.scoring), "fit": [*split.train, *split.validation]}
    return {
        "scored": list(split.validation),
        "fit": list(split.train[: settings["train_repos"]]),
    }


def filler_job(job: tuple[str, int, str]) -> dict[str, tuple[np.ndarray, ...]]:
    """One filler row (cold or meta start) adapting online from zero on every scored repo."""
    kind, seed, which = job
    filler = filler_of(kind, seed)
    start = cold_start(filler)
    if which == "meta":
        start = start.with_vector(SETTINGS["starts"][(kind, seed)])
    return {
        r: online_risks(filler, start, DATA[r].episode, PRIMARY_COST) for r in SETTINGS["scored"]
    }


def classifier_rows(fit: list[str], scored: list[str]) -> dict[str, dict[str, Any]]:
    """The pool classifier, fixed and with the fillers' online calibrator."""
    features = np.vstack([DATA[r].all_features() for r in fit])
    labels = np.concatenate([DATA[r].all_followed() for r in fit]).astype(float)
    model = fit_logistic(features, labels, CLASSIFIER_L2)
    fixed, adapting = {}, {}
    for repo in scored:
        probabilities = tuple(predict(model, x) for x in DATA[repo].episode.features)
        fixed[repo] = probabilities
        adapting[repo] = calibrated_risks(probabilities, DATA[repo].episode.followed, PRIMARY_COST)
    return {CLASSIFIER: fixed, ADAPTING_CLASSIFIER: adapting}


def traces_of(by_repo: dict[str, Any], scored: list[str]) -> tuple:
    """Every scored repository's sessions as note traces, in replay order."""
    return tuple(
        trace
        for r in scored
        for trace in note_traces(r, DATA[r].episode.followed, by_repo[r], DATA[r].boundary)
    )


def all_arms(repos: dict[str, list[str]], seeds: list[int]) -> dict[str, dict[int, tuple]]:
    """Every row's traces on the scored repositories, keyed by row and seed."""
    scored = repos["scored"]
    jobs = [(k, s, w) for k in FILLERS for w in ("cold", "meta") for s in seeds]
    done = dict(zip(jobs, g6.pool_map(filler_job, jobs, len(jobs)), strict=True))
    arms: dict[str, dict[int, tuple]] = {
        COUNTERS: {0: traces_of({r: DATA[r].counters_risk for r in scored}, scored)}
    }
    for name, by_repo in classifier_rows(repos["fit"], scored).items():
        arms[name] = {0: traces_of(by_repo, scored)}
    for (kind, seed, which), by_repo in done.items():
        arms.setdefault(f"{kind} {which} start", {})[seed] = traces_of(by_repo, scored)
    return arms


def score(args: argparse.Namespace) -> None:
    """Score every row on the evaluation repositories and write the results file."""
    started = time.time()
    if args.on == "scoring" and not args.scored:
        raise SystemExit("the scoring fold is read only with --scored and a frozen prereg")
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=PREREG_NAME)
    prepare(args)
    trained = json.loads(Path(args.starts).with_suffix(".json").read_text())
    stored = np.load(args.starts)
    picked = best_starts(args.starts)
    seeds = sorted({seed for _, seed in picked})
    SETTINGS["starts"] = {
        key: stored[start_key(*key, p["rule"], p["outer_rate"])] for key, p in picked.items()
    }
    repos = evaluation_repos(args, trained)
    SETTINGS["scored"] = repos["scored"]
    body = meta_report(all_arms(repos, seeds), seed=sel.SEED)
    for line in body["table_rows"]:
        log.info(line)
    document = {
        **label,
        "asks": "does a meta-learned start adapt better from the first outcomes on new repos",
        "evaluated_on": args.on,
        "code_commit": t36.git_head(),
        "train_code_commit": trained["code_commit"],
        "split": {k: len(v) for k, v in vars(SPLIT[0]).items()},
        "meta_train_repos": trained["train_repos"],
        "outer_steps_max": trained["outer_steps"],
        "classifier_fit_repos": len(repos["fit"]),
        "chosen_starts": [{"filler": k, "seed": s, **p} for (k, s), p in sorted(picked.items())],
        **body,
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


def parser_of() -> argparse.ArgumentParser:
    """The command line: `train` and `score`."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    train_parser, score_parser = sub.add_parser("train"), sub.add_parser("score")
    for each in (train_parser, score_parser):
        for name in ("episodes", "pool", "out"):
            each.add_argument(f"--{name}", required=True)
    train_parser.add_argument("--seeds", type=int, nargs="+", default=list(sel.WIRING_SEEDS))
    train_parser.add_argument("--outer-steps", type=int, default=300)
    train_parser.add_argument("--train-repos", type=int, default=70)
    train_parser.add_argument("--workers", type=int, default=16)
    score_parser.add_argument("--starts", required=True)
    score_parser.add_argument("--on", choices=("validation", "scoring"), required=True)
    score_parser.add_argument("--scored", action="store_true")
    score_parser.add_argument("--prereg")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run one subcommand."""
    args = parser_of().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    {"train": train, "score": score}[args.cmd](args)


if __name__ == "__main__":
    main()
