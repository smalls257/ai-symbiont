"""The scored T39 comparison (prereg/2026-10-28-meta-start.md). Periphery script.

Primary: Pillow, dvc and conan, each replayed whole from empty history, every row adapting
online from zero. Secondary: pool fold 0, re-used (T46's exploratory curve scored cold rows
there). Every setting (start, calibrator rate, thresholds) comes from the validation
repositories; nothing is fit on a scoring repository. Rules: `symbiont.eval.meta_start_scored`.

    run_meta_start_scored.py --episodes data/t39-episodes.npz --held-out data/t39-held-out.npz \
        --pool results/repo-pool.json --starts data/t39-starts.npz --out results/meta-start.json \
        --scored --prereg prereg/2026-10-28-meta-start.md

PYTHONPATH: src and scripts/offline. Set OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1.
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import meta_start_episodes as eps
import numpy as np
import run_meta_start as rms
import run_penalized as t36
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.meta_start import EARLY_SESSIONS, calibrated_risks, cold_start, online_risks
from symbiont.eval.meta_start_scored import ADAPTING, COUNTERS, FIXED, Window, meta_scored_report
from symbiont.eval.net_benefit import PRIMARY_COST
from symbiont.eval.note_cost_logistic import fit_logistic, predict
from symbiont.eval.note_delivery import NoteTrace
from symbiont.eval.prereg_git import run_provenance

log = logging.getLogger("t39-scored")
SETS: dict[str, dict[str, eps.RepoSteps]] = {}  # "validation", "held-out", "fold 0"
EARLY, LATE = "first 10 sessions", "after 10 sessions"


def filler_job(job: tuple[str, int, str]) -> dict[str, dict[str, tuple[np.ndarray, ...]]]:
    """One filler row adapting online from zero on every repository of every set."""
    kind, seed, which = job
    chosen = rms.SETTINGS["chosen"][which][(kind, seed)]
    filler = rms.filler_of(kind, seed, chosen["calibrator_rate"])
    start = cold_start(filler)
    if which == "meta":
        start = start.with_vector(rms.SETTINGS["starts"][(kind, seed)])
    log.info("%s seed %d %s start", kind, seed, which)
    return {
        name: {
            r: online_risks(filler, start, steps.episode, PRIMARY_COST)
            for r, steps in repos.items()
        }
        for name, repos in SETS.items()
    }


def classifier_risks() -> dict[str, dict[str, dict[str, Any]]]:
    """The classifier fit on the 80 non-scoring pool repositories, fixed and adapting."""
    fit = [*rms.SPLIT[0].train, *rms.SPLIT[0].validation]
    model = fit_logistic(
        np.vstack([rms.DATA[r].all_features() for r in fit]),
        np.concatenate([rms.DATA[r].all_followed() for r in fit]).astype(float),
        rms.CLASSIFIER_L2,
    )
    rms.SETTINGS["classifier"] = rms.classifier_calibrator_rate(model)
    rate = rms.SETTINGS["classifier"]["calibrator_rate"]
    rows: dict[str, dict[str, dict[str, Any]]] = {FIXED: {}, ADAPTING: {}}
    for name, repos in SETS.items():
        fixed = {r: tuple(predict(model, x) for x in s.episode.features) for r, s in repos.items()}
        rows[FIXED][name] = fixed
        rows[ADAPTING][name] = {
            r: calibrated_risks(fixed[r], repos[r].episode.followed, PRIMARY_COST, rate)
            for r in repos
        }
    return rows


def unit_of(set_name: str, repo: str, steps: eps.RepoSteps, index: int, window: str) -> str:
    """The resampling unit of one session (see the prereg, section Metrics)."""
    if set_name != "held-out":
        return repo  # fold 0 and validation: the repository
    task = steps.task_ids[index]
    return f"{task}#{index}" if window == EARLY else task


def traces(set_name: str, risks: dict[str, tuple[np.ndarray, ...]], window: str) -> tuple:
    """One row's sessions of one set inside `window`, as note traces."""
    found = []
    for repo, steps in SETS[set_name].items():
        for index, (y, r, b) in enumerate(
            zip(steps.episode.followed, risks[repo], steps.boundary, strict=True)
        ):
            if (index < EARLY_SESSIONS) != (window == EARLY):
                continue
            unit = unit_of(set_name, repo, steps, index, window)
            found.append(
                NoteTrace(unit, tuple(map(bool, y)), tuple(map(float, r)), tuple(map(bool, b)))
            )
    return tuple(found)


def all_risks(seeds: list[int]) -> dict[str, dict[int, dict[str, Any]]]:
    """Every row's risks on every set: row -> seed -> set -> repository -> per session."""
    jobs = [(k, s, w) for k in rms.FILLERS for w in ("cold", "meta") for s in seeds]
    done = g6.pool_map(filler_job, jobs, min(len(jobs), rms.SETTINGS["workers"]))
    found: dict[str, dict[int, dict[str, Any]]] = {
        COUNTERS: {
            0: {n: {r: s.counters_risk for r, s in repos.items()} for n, repos in SETS.items()}
        }
    }
    for name, by_set in classifier_risks().items():
        found[name] = {0: by_set}
    for (kind, seed, which), by_set in zip(jobs, done, strict=True):
        found.setdefault(f"{kind} {which} start", {})[seed] = by_set
    return found


def windows_of(risks: dict[str, dict[int, dict[str, Any]]], scored_set: str) -> dict[str, Window]:
    """Both windows of one scoring set, each row paired with its validation traces."""
    found = {}
    for window in (EARLY, LATE):
        rows = {
            name: {
                seed: (
                    traces("validation", by_set["validation"], window),
                    traces(scored_set, by_set[scored_set], window),
                )
                for seed, by_set in by_seed.items()
            }
            for name, by_seed in risks.items()
        }
        units = {t.task_id for t in rows[COUNTERS][0][1]}
        repo_of = {u: repo_for(scored_set, u) for u in units}
        unit = (
            "repository" if scored_set != "held-out" else ("session" if window == EARLY else "task")
        )
        found[window] = Window(rows, repo_of, unit)
    return found


def repo_for(scored_set: str, unit: str) -> str:
    """The stratum a unit is resampled within: its repository, or one stratum for fold 0."""
    if scored_set != "held-out":
        return "pool fold 0"
    task = unit.split("#")[0]
    return next(r for r, s in SETS["held-out"].items() if task in s.task_ids)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """Load both episode files, the split and the validation choices; fingerprint the starts."""
    rms.prepare(args)
    held = eps.load(args.held_out)
    split = rms.SPLIT[0]
    SETS.update(
        {
            "validation": {r: rms.DATA[r] for r in split.validation},
            "held-out": held,
            "fold 0": {r: rms.DATA[r] for r in split.scoring},
        }
    )
    stored = np.load(args.starts)
    chosen = rms.SETTINGS["chosen"] = rms.chosen_settings(args.starts)
    rms.SETTINGS["starts"] = {
        key: stored[rms.start_key(*key, p["rule"], p["outer_rate"], p["calibrator_rate"])]
        for key, p in chosen["meta"].items()
    }
    rms.SETTINGS["workers"] = args.workers
    return {
        "starts_sha256": hashlib.sha256(Path(args.starts).read_bytes()).hexdigest(),
        "held_out_counts": json.loads(Path(args.held_out).with_suffix(".json").read_text()),
    }


def run(args: argparse.Namespace) -> None:
    """Score both sets and write the results file."""
    started = time.time()
    if not args.scored:
        raise SystemExit(
            "the held-out repositories are read only with --scored and a frozen prereg"
        )
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=rms.PREREG_NAME)
    facts = prepare(args)
    chosen = rms.SETTINGS["chosen"]
    risks = all_risks(sorted({seed for _, seed in chosen["meta"]}))
    primary = meta_scored_report(windows_of(risks, "held-out"), seed=sel.SEED)
    secondary = meta_scored_report(windows_of(risks, "fold 0"), seed=sel.SEED)
    for line in primary["table_rows"]:
        log.info(line)
    document = {
        **label,
        "asks": "does a meta-learned start adapt better on repos never seen",
        "code_commit": t36.git_head(),
        **facts,
        "chosen_on_validation": {
            which: [{"filler": k, "seed": s, **p} for (k, s), p in sorted(by_key.items())]
            for which, by_key in chosen.items()
        }
        | {"adapting_classifier": rms.SETTINGS["classifier"]},
        "primary_held_out": primary,
        "secondary_fold_0_reused": secondary,
        "wall_clock_s": time.time() - started,
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # Compact: the indented scored file was over the 1 MB limit for tracked files.
    Path(args.out).write_text(json.dumps(document, separators=(",", ":")) + "\n")
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for name in ("episodes", "held-out", "pool", "starts", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--scored", action="store_true")
    parser.add_argument("--prereg")
    parser.add_argument("--workers", type=int, default=10)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
