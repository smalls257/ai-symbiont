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
from meta_start_checkpoints import JobCheckpoint

from symbiont.core.dense import DenseNet
from symbiont.core.meta import MetaLearnable
from symbiont.core.mushroom import Mushroom
from symbiont.eval import selection as sel
from symbiont.eval.meta_start import (
    Checkpoints,
    MetaConfig,
    MetaRule,
    MetaSplit,
    calibrated_risks,
    cold_start,
    meta_split,
    meta_train,
    online_risks,
    weighted_log_loss,
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
    MetaRule.REPTILE: (0.01, 0.03, 0.1, 0.3),
}
# Calibrator rates, fixed per run and chosen on the validation repositories for every row with
# a calibrator (controller ruling, Oct 28: a grid choice, not a self-tuned rate).
CALIBRATOR_RATES = (0.05, 0.1, 0.2, 0.5)
CHECK_EVERY = 5  # outer steps between validation checks (controller ruling, Oct 28)
PATIENCE = 20  # checks without improvement: 100 outer steps, as 5 checks of 20 before
FILLERS = ("fly", "dense")
DATA: dict[str, eps.RepoSteps] = {}
SPLIT: list[MetaSplit] = []
SETTINGS: dict[str, Any] = {}


def filler_of(kind: str, seed: int, calibrator_rate: float) -> MetaLearnable:
    """The fly (T36 rate) or DenseNet (T46 rate) with this wiring seed and calibrator rate."""
    if kind == "fly":
        return Mushroom(seed, lr=sel.LEARNING_RATE, calibrator_rate=calibrator_rate)
    if kind == "dense":
        return DenseNet(seed, lr=DENSE_RATE, calibrator_rate=calibrator_rate)
    raise ValueError(f"unknown filler {kind!r}")


Job = tuple[str, int, MetaRule, float, float]


def train_job(job: Job) -> dict[str, Any]:
    """Meta-train one filler under one rule, step size and calibrator rate; resumable."""
    kind, seed, rule, rate, calibrator_rate = job
    filler, split = filler_of(kind, seed, calibrator_rate), SPLIT[0]
    key = start_key(kind, seed, rule.name, rate, calibrator_rate)
    saved = JobCheckpoint(SETTINGS["checkpoints"], key)
    finished = saved.done()
    if finished is not None:
        log.info("%s: already done", key)
        return finished
    started, resume = time.time(), saved.resume_from(cold_start(filler))
    train = [DATA[r].episode for r in split.train[: SETTINGS["train_repos"]]]
    validation = [DATA[r].episode for r in split.validation]
    config = MetaConfig(
        rate,
        rule,
        outer_steps=SETTINGS["outer_steps"],
        check_every=CHECK_EVERY,
        patience=PATIENCE,
        seed=seed,
    )
    result = meta_train(filler, train, validation, config, Checkpoints(resume, saved.save_progress))
    seconds = time.time() - started
    log.info(
        "%s: best step %d loss %.4f (cold %.4f) %.0fs%s",
        *(key, result.best_step, result.best_loss, result.curve[0][1], seconds),
        "" if resume is None else f" (resumed at step {resume.step})",
    )
    document = {
        "kind": kind,
        "seed": seed,
        "rule": rule.name,
        "outer_rate": rate,
        "calibrator_rate": calibrator_rate,
        "best_step": result.best_step,
        "curve": [list(c) for c in result.curve],
        "start": result.start.as_vector().tolist(),
        "seconds": seconds,
    }
    saved.save_done(document)
    return document


def train(args: argparse.Namespace) -> None:
    """Every (filler, seed, rule, step size) job; starts to npz, curves to json."""
    prepare(args)
    checkpoints = args.checkpoints or str(Path(args.out).with_suffix("")) + "-jobs"
    SETTINGS.update(
        train_repos=args.train_repos, outer_steps=args.outer_steps, checkpoints=checkpoints
    )
    grid = [(rule, rate) for rule, rates in OUTER_GRID.items() for rate in rates]
    jobs: list[Job] = [
        (k, s, *g, c)
        for k in FILLERS
        for s in args.seeds
        for g in grid
        for c in args.calibrator_rates
    ]
    jobs.sort(key=lambda job: job[0] != "fly")  # the fly's jobs are the long ones
    done = g6.pool_map(train_job, jobs, args.workers)
    starts = {
        start_key(d["kind"], d["seed"], d["rule"], d["outer_rate"], d["calibrator_rate"]): np.array(
            d.pop("start")
        )
        for d in done
    }
    np.savez(args.out, **starts)
    kept = {k: SETTINGS[k] for k in ("train_repos", "outer_steps", "checkpoints")}
    summary = {"code_commit": t36.git_head(), **kept, "jobs": done}
    Path(args.out).with_suffix(".json").write_text(json.dumps(summary, indent=1))
    log.info("wrote %s", args.out)


def start_key(kind: str, seed: int, rule: str, rate: float, calibrator_rate: float) -> str:
    """The name of one trained start in the starts file."""
    return f"{kind}.{seed}.{rule}.{rate:g}.cal{calibrator_rate:g}"


def prepare(args: argparse.Namespace) -> None:
    """Load the episodes and fix the split; the forked workers inherit both."""
    pool = json.loads(Path(args.pool).read_text())["repos"]
    SPLIT[:] = [meta_split(pool)]
    DATA.update(eps.load(args.episodes))


def chosen_settings(path: str) -> dict[str, dict[tuple[str, int], dict[str, Any]]]:
    """Per (filler, seed), chosen on validation loss only.

    Meta start: the rule, step size, calibrator rate and check with the lowest loss. Cold start:
    the calibrator rate whose untrained start (check 0) has the lowest loss.
    """
    jobs = json.loads(Path(path).with_suffix(".json").read_text())["jobs"]
    meta: dict[tuple[str, int], dict[str, Any]] = {}
    cold: dict[tuple[str, int], dict[str, Any]] = {}
    for job in jobs:
        key, loss, untrained = (
            (job["kind"], job["seed"]),
            min(p[1] for p in job["curve"]),
            job["curve"][0][1],
        )
        if key not in meta or loss < meta[key]["validation_loss"]:
            fields = ("rule", "outer_rate", "calibrator_rate", "best_step")
            meta[key] = {f: job[f] for f in fields} | {"validation_loss": loss}
        if key not in cold or untrained < cold[key]["validation_loss"]:
            cold[key] = {"calibrator_rate": job["calibrator_rate"], "validation_loss": untrained}
    return {"meta": meta, "cold": cold}


def evaluation_repos(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, list[str]]:
    """Which repositories are scored; the classifier always fits the starts' training repos.

    The scoring fold is read only in a scored run; a smoke run scores validation.
    """
    split = SPLIT[0]
    scored = split.scoring if args.on == "scoring" else split.validation
    return {"scored": list(scored), "fit": list(split.train[: settings["train_repos"]])}


def filler_job(job: tuple[str, int, str]) -> dict[str, tuple[np.ndarray, ...]]:
    """One filler row (cold or meta start) adapting online from zero on every scored repo."""
    kind, seed, which = job
    chosen = SETTINGS["chosen"][which][(kind, seed)]
    filler = filler_of(kind, seed, chosen["calibrator_rate"])
    start = cold_start(filler)
    if which == "meta":
        start = start.with_vector(SETTINGS["starts"][(kind, seed)])
    return {
        r: online_risks(filler, start, DATA[r].episode, PRIMARY_COST) for r in SETTINGS["scored"]
    }


def classifier_calibrator_rate(model: Any) -> dict[str, float]:
    """The calibrator rate whose adapting classifier has the lowest validation loss."""
    losses = {}
    for rate in CALIBRATOR_RATES:
        parts = []
        for repo in SPLIT[0].validation:
            early = DATA[repo].episode.early()
            probabilities = [predict(model, x) for x in early.features]
            risks = calibrated_risks(probabilities, early.followed, PRIMARY_COST, rate)
            parts += [
                weighted_log_loss(r, y, PRIMARY_COST)
                for r, y in zip(risks, early.followed, strict=True)
            ]
        losses[rate] = float(np.concatenate(parts).mean())
    best = min(losses, key=lambda rate: (losses[rate], rate))
    return {"calibrator_rate": best, "validation_loss": losses[best]}


def classifier_rows(fit: list[str], scored: list[str]) -> dict[str, dict[str, Any]]:
    """The pool classifier, fixed and with the fillers' online calibrator."""
    features = np.vstack([DATA[r].all_features() for r in fit])
    labels = np.concatenate([DATA[r].all_followed() for r in fit]).astype(float)
    model = fit_logistic(features, labels, CLASSIFIER_L2)
    SETTINGS["classifier"] = classifier_calibrator_rate(model)
    rate = SETTINGS["classifier"]["calibrator_rate"]
    fixed, adapting = {}, {}
    for repo in scored:
        probabilities = tuple(predict(model, x) for x in DATA[repo].episode.features)
        fixed[repo] = probabilities
        adapting[repo] = calibrated_risks(
            probabilities, DATA[repo].episode.followed, PRIMARY_COST, rate
        )
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
    chosen = SETTINGS["chosen"] = chosen_settings(args.starts)
    seeds = sorted({seed for _, seed in chosen["meta"]})
    SETTINGS["starts"] = {
        key: stored[start_key(*key, p["rule"], p["outer_rate"], p["calibrator_rate"])]
        for key, p in chosen["meta"].items()
    }
    repos = evaluation_repos(args, trained)
    SETTINGS["scored"] = repos["scored"]
    body = meta_report(all_arms(repos, seeds), seed=sel.SEED)
    for line in body["table_rows"]:
        log.info(line)
    document = {
        **label,
        "asks": "does a meta-learned start adapt better on repos never seen",
        "evaluated_on": args.on,
        "code_commit": t36.git_head(),
        "train_code_commit": trained["code_commit"],
        "split": {k: len(v) for k, v in vars(SPLIT[0]).items()},
        "meta_train_repos": trained["train_repos"],
        "outer_steps_max": trained["outer_steps"],
        "classifier_fit_repos": len(repos["fit"]),
        "chosen_on_validation": {
            which: [{"filler": k, "seed": s, **p} for (k, s), p in sorted(by_key.items())]
            for which, by_key in chosen.items()
        }
        | {"adapting_classifier": SETTINGS["classifier"]},
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
    train_parser.add_argument("--workers", type=int, default=10)
    train_parser.add_argument(
        "--calibrator-rates", type=float, nargs="+", default=list(CALIBRATOR_RATES)
    )
    train_parser.add_argument(
        "--checkpoints", help="job checkpoint directory (default: next to --out)"
    )
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
