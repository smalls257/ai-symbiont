"""Why do the fly and DenseNet trail a batch classifier? The T47 ablation (exploratory).

Inside the 100-repository pool only (`results/repo-pool.json`): pool fold 0 is scored, the
other 80 repositories train. Each arm (`fly_ablation_arms`) learns online over the first N
training repositories in pool order, then every scoring repository is replayed from that
shipped state under two regimes (`symbiont.eval.regime_replay`): R1 live-only and R2 refit
between sessions. The batch classifier and the MLP ceiling probe are fit on the same N
repositories (the MLP stops early on the last eight). Counters run through the real replay.
Every row is scored under option A by cross-validation grouped by scoring repository
(`symbiont.eval.note_cost_report`), the counters row beside it.

The fast path replays features, not records; a check at start replays the existing fly and
DenseNet through the real `offline.replay` on one training repository and refuses to go on
unless the risks agree.

    run_fly_ablation.py --pool results/repo-pool.json --data-dir data/nebius-openhands/pool \
        --part main --out data/fly-ablation-main.json --workers 10

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

import fly_ablation_arms as fa
import fly_ablation_score as score
import numpy as np
import run_penalized as t36
import run_repo_curve as rc
import run_selection as g6

from symbiont.core.features import FEATURE_NAMES
from symbiont.core.fly_variants import FlyVariant
from symbiont.core.input_gain import fit_input_gain
from symbiont.eval import learner_diagnostics as diag
from symbiont.eval import selection as sel
from symbiont.eval.batch_refit import REFIT_PRIOR, LogisticScorer, map_logistic, trouble_weights
from symbiont.eval.note_cost_logistic import fit_logistic
from symbiont.eval.regime_replay import (
    Project,
    frozen_risks,
    live_risks,
    refit_risks,
    train_online,
)
from symbiont.eval.tanh_net import NetScorer, fine_tune, fit_mlp

log = logging.getLogger("fly-ablation")
L2 = 100.0  # the T46 classifier's penalty
VALID_REPOS = 8  # the MLP's early-stopping slice: the last eight training repositories
DIAG_SAMPLE = 4000
PROJECTS: dict[str, Project] = {}
FIXED: dict[int, fa.Fixed] = {}
PARTS = {
    "main": {"n": (80,), "arms": tuple(fa.ARMS), "mlp": True},
    "curve": {
        "n": (1, 10),
        "arms": ("fly as is", "fly combined", "fly H1+H2", "dense combined"),
        "mlp": False,
    },
}


def build_projects() -> None:
    """Feature rows and labels per session of every pool repository, from the warmed columns."""
    for repo, columns in rc.COLUMNS.items():
        rows, start, sessions = columns["features"], 0, []
        for followed in columns["followed"]:
            stop = start + len(followed)
            sessions.append((rows[start:stop], np.asarray(followed, dtype=bool)))
            start = stop
        PROJECTS[repo] = Project(repo, tuple(sessions))


def fix_for(n_repos: int) -> fa.Fixed:
    """Input gain and trouble share of the first N training repositories."""
    train = rc.TRAIN_ORDER[:n_repos]
    rows = np.vstack([rc.COLUMNS[r]["features"] for r in train])
    labels = np.concatenate([labels for r in train for _, labels in PROJECTS[r].sessions])
    return fa.Fixed(gain=fit_input_gain(rows), trouble_share=float(labels.mean()))


def by_repo(risks_of: Any) -> dict[str, list[float]]:
    """Flat risks per scoring repository."""
    return {r: np.concatenate(risks_of(PROJECTS[r])).tolist() for r in rc.SCORING}


def online_job(job: tuple[str, int, int]) -> dict[str, Any]:
    """Ship an arm from the first N training repositories, then score R1 and R2."""
    name, seed, n_repos = job
    started, arm = time.time(), fa.ARMS[name]
    scorer = arm.build(seed, FIXED[n_repos])
    shipped = train_online(
        scorer, [PROJECTS[r] for r in rc.TRAIN_ORDER[:n_repos]], scorer.initial_state(0)
    )
    times: list[float] = []
    reader, refit = fa.refit_for(arm, scorer, shipped)
    out = {
        "R1": by_repo(lambda project: live_risks(scorer, project, shipped)),
        "R2": by_repo(
            lambda project: refit_risks(reader, fa.timed(refit, times), project, shipped)
        ),
        "refit_s": times,
    }
    log.info("%s seed %d n=%d (%.0fs)", name, seed, n_repos, time.time() - started)
    return out


def logistic_job(n_repos: int) -> dict[str, Any]:
    """The batch classifier: R1 frozen, R2 refit toward the shipped coefficients."""
    train = rc.TRAIN_ORDER[:n_repos]
    rows = np.vstack([rc.COLUMNS[r]["features"] for r in train])
    labels = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in train]).astype(
        float
    )
    model, share = fit_logistic(rows, labels, L2), float(labels.mean())
    scorer, times = LogisticScorer(model), []

    def refit(encoded: list[np.ndarray], followed: list[np.ndarray]) -> np.ndarray:
        found = np.concatenate(followed)
        return map_logistic(
            np.vstack(encoded),
            found.astype(float),
            trouble_weights(found, share),
            model.coef,
            REFIT_PRIOR,
        )

    return {
        "R1": by_repo(lambda project: frozen_risks(scorer, project, model.coef)),
        "R2": by_repo(
            lambda project: refit_risks(scorer, fa.timed(refit, times), project, model.coef)
        ),
        "refit_s": times,
    }


def mlp_job(job: tuple[int, int]) -> dict[str, Any]:
    """The MLP ceiling probe: R1 frozen, R2 fine-tuned toward the shipped weights."""
    seed, n_repos = job
    shipped_from = rc.TRAIN_ORDER[:n_repos]
    train, valid = shipped_from[:-VALID_REPOS], shipped_from[-VALID_REPOS:]

    def stack(repos: list[str]) -> tuple[np.ndarray, np.ndarray]:
        rows = np.vstack([rc.COLUMNS[r]["features"] for r in repos])
        return rows, np.concatenate(
            [np.concatenate(rc.COLUMNS[r]["followed"]) for r in repos]
        ).astype(bool)

    net, times = fit_mlp(stack(train), stack(valid), seed), []
    weights = trouble_weights(np.array([True, False]), FIXED[n_repos].trouble_share)

    def refit(encoded: list[np.ndarray], followed: list[np.ndarray]) -> Any:
        found = np.concatenate(followed)
        rows = np.vstack(encoded)
        return fine_tune(net, rows, found, np.where(found, weights[0], weights[1]), REFIT_PRIOR)

    raw = _RawNet()
    log.info("mlp seed %d n=%d", seed, n_repos)
    return {
        "R1": by_repo(lambda project: frozen_risks(raw, project, net)),
        "R2": by_repo(lambda project: refit_risks(raw, fa.timed(refit, times), project, net)),
        "refit_s": times,
    }


class _RawNet(NetScorer):
    """Encodes nothing, so a refit receives raw rows and applies the network's own gain."""

    def encode(self, rows: np.ndarray, net: Any) -> np.ndarray:
        return np.atleast_2d(rows)

    def step_risks(self, encoded: np.ndarray, net: Any) -> np.ndarray:
        return super().step_risks(super().encode(encoded, net), net)


def counters_job(n_repos: int) -> dict[str, Any]:
    """Counters through the real replay (R1 only: counters have no refit)."""
    return {"R1": rc.curve_job(("counters", 0, None, n_repos))}


def run_job(job: tuple[str, Any]) -> tuple[tuple[str, Any], dict[str, Any]]:
    """Dispatch one job in a forked worker."""
    kind, key = job
    found = {
        "online": online_job,
        "logistic": logistic_job,
        "mlp": mlp_job,
        "counters": counters_job,
    }[kind](key)
    return job, found


def jobs_of(part: dict[str, Any]) -> list[tuple[str, Any]]:
    """Longest first: the online arms on the most repositories."""
    jobs: list[tuple[str, Any]] = []
    for n in sorted(part["n"], reverse=True):
        jobs += [("online", (a, s, n)) for a in part["arms"] for s in sel.WIRING_SEEDS]
        jobs += [("counters", n), ("logistic", n)]
        jobs += [("mlp", (s, n)) for s in sel.WIRING_SEEDS] if part["mlp"] else []
    return jobs


def check_fast_path() -> dict[str, float]:
    """The existing fly and DenseNet, real replay against the fast path, one training repository."""
    found = {}
    for kind, name, param in (
        ("mushroom", "fly as is", None),
        ("dense", "DenseNet as is", fa.CURVE_DENSE_RATE),
    ):
        real = rc.curve_job((kind, 0, param, 1))
        fast = online_job((name, 0, 1))["R1"]
        gap = max(float(np.max(np.abs(np.subtract(real[r], fast[r])))) for r in rc.SCORING)
        if gap > 1e-9:
            raise RuntimeError(f"fast path differs from the real replay for {name}: {gap:g}")
        found[name] = gap
    return found


def diagnostics() -> dict[str, Any]:
    """H1, H2, H4 and D1 measured on the training repositories (seed 0)."""
    fixed, train = FIXED[80], rc.TRAIN_ORDER
    rows = np.vstack([rc.COLUMNS[r]["features"] for r in train])
    sample = rows[np.random.default_rng(sel.SEED).choice(len(rows), DIAG_SAMPLE, replace=False)]
    watched = FEATURE_NAMES.index("lines_added_session")
    found: dict[str, Any] = {"trouble_share_train": fixed.trouble_share}
    for label, gain in (("raw", None), ("gain", fixed.gain)):
        fly = FlyVariant(0, gain=gain)
        state = fly.initial_state(0)
        found[f"fly_code_{label}"] = diag.fly_code_report(fly, state, sample, watched)
        found[f"fly_memory_{label}"] = _memory(fly, state, train)
    for name in ("dense plain delta", "dense D1 gain", "dense D1 gain fan-in"):
        dense = fa.ARMS[name].build(0, fixed)
        found[f"saturation {name}"] = diag.saturation_share(dense, dense.initial_state(0), sample)
    return found


def _memory(fly: FlyVariant, state: Any, train: list[str]) -> dict[str, Any]:
    codes, followed = [], []
    for repo in train:
        for rows, labels in PROJECTS[repo].sessions:
            codes.append(fly.encode(rows, state).astype(np.int16))
            followed.append(labels)
    stacked, labels_all = np.vstack(codes), np.concatenate(followed)
    relax = min(1.0, 0.1 * fly.false_alarm_cost)
    return {
        f"rate {rate:g}": diag.cell_memory(stacked, labels_all, rate, relax)
        for rate in (0.1, fa.SLOW_RATE)
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """Load the pool and fix the gains for every N of the part."""
    sizes = rc.prepare(
        argparse.Namespace(pool=args.pool, data_dir=args.data_dir, workers=args.workers)
    )
    build_projects()
    for n in (1, 10, 80):
        FIXED[n] = fix_for(n)
    return sizes


def run(args: argparse.Namespace) -> None:
    """Check, run every job of the part, score and write."""
    started = time.time()
    sizes = prepare(args)
    checked = check_fast_path()
    log.info("pool ready %s, fast path agrees %s (%.0fs)", sizes, checked, time.time() - started)
    part = PARTS[args.part]
    found = dict(g6.pool_map(run_job, jobs_of(part), args.workers))
    document = {
        "run_label": "exploratory",
        "asks": "why the fly and DenseNet trail a batch classifier, by mechanism and regime",
        "part": args.part,
        "code_commit": t36.git_head(),
        "pool": args.pool,
        **sizes,
        "fast_path_max_gap": checked,
        "diagnostics": diagnostics() if args.part == "main" else None,
        **score.scored(found, part, args.workers),
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (wall clock %.0fs)", args.out, time.time() - started)


def main() -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("pool", "data-dir", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--part", choices=sorted(PARTS), required=True)
    parser.add_argument("--workers", type=int, default=8)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
