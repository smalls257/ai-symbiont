"""T48 confirm run on tox, dask and PyBaMM: counts, then the settings shipped from the pool.

prereg/2026-10-28-confirm.md describes the run. Learners ship from the pool and note thresholds
are chosen on the pool scoring repositories, then fixed; only DenseNet R2 refits on the confirm
repositories. `counts` prints counts only. Set OMP_NUM_THREADS=1.
Usage: run_confirm_scored.py {counts|ship|score} --confirm-dir ... --pool ... --out ...
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import confirm_score as cs
import numpy as np
import run_fly_ablation as ra
import run_penalized as t36
import run_repo_curve as rc
import run_selection as g6

from symbiont.eval import confirm_report as cr
from symbiont.eval import selection as sel
from symbiont.eval.note_cost_report import NET, scored
from symbiont.eval.note_cost_scored_report import PRIMARY, registered_options
from symbiont.eval.offline import drop_taskless
from symbiont.eval.prereg_git import run_provenance
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError

log = logging.getLogger("confirm")
CONFIRM = cs.CONFIRM
settings_of = cs.settings_of  # the ship step and the scored check share one definition
SHIPPED_FROM = 80  # every T47 pool training repository
# (row, arm in the T47 runner, regime): the registered rows, plainest first.
ROWS = (
    ("logistic regression", None, "R1"),
    ("DenseNet combined", "dense combined backprop", "R2"),
    ("fly as is", "fly as is", "R1"),
    ("fly combined", "fly combined", "R1"),
)


def repo_counts(path: Path, repo: str) -> dict[str, int]:
    """Refused rows, then tasks, sessions and steps of the readable rows (no text)."""
    rows = list(openhands.read_each_row(path, repo))
    readable = [row for row in rows if not isinstance(row, ReadError)]
    records = [record for row in readable for record in row]
    sessions, taskless = drop_taskless(sel.group_sessions(records))
    return {
        "trajectories_refused": len(rows) - len(readable),
        "trajectories_readable": len(readable),
        "sessions_without_task": taskless,
        "tasks": len({s[0].task_id for s in sessions}),
        "sessions": len(sessions),
        "steps": sum(len(s) for s in sessions),
    }


def counts(args: argparse.Namespace) -> None:
    """Counts of every confirm repository, before any label, risk or metric."""
    found = {
        repo: repo_counts(Path(args.confirm_dir) / (repo.replace("/", "__") + ".jsonl"), repo)
        for repo in CONFIRM
    }
    Path(args.out).write_text(json.dumps({"run_label": "counts only", "repos": found}, indent=1))
    for repo, numbers in found.items():
        log.info("%s %s", repo, numbers)


def pool_risks(job: tuple[str, Any]) -> tuple[tuple[str, Any], dict[str, list[float]]]:
    """One shipped learner's risks on the 20 pool scoring repositories."""
    kind, key = job
    if kind == "counters":
        return job, rc.curve_job(("counters", 0, None, SHIPPED_FROM))
    if kind == "logistic":
        return job, ra.logistic_job(SHIPPED_FROM)["R1"]
    arm, seed, regime = key
    return job, ra.online_job((arm, seed, SHIPPED_FROM))[regime]


def ship_jobs() -> list[tuple[str, Any]]:
    """Counters, the classifier, and every online row per wiring seed."""
    jobs: list[tuple[str, Any]] = [("counters", None), ("logistic", None)]
    for _, arm, regime in ROWS:
        if arm is not None:
            jobs += [("online", (arm, seed, regime)) for seed in sel.WIRING_SEEDS]
    return jobs


def row_of(job: tuple[str, Any]) -> tuple[str, int]:
    """The registered row and wiring seed of a ship job."""
    kind, key = job
    if kind in ("counters", "logistic"):
        return ("counters" if kind == "counters" else "logistic regression"), 0
    arm, seed, _ = key
    return next(row for row, a, _ in ROWS if a == arm), seed


def ship(args: argparse.Namespace) -> None:
    """Ship every row from the 80 pool training repositories and fix its thresholds."""
    started = time.time()
    ra.prepare(argparse.Namespace(pool=args.pool, data_dir=args.data_dir, workers=args.workers))
    found = dict(g6.pool_map(pool_risks, ship_jobs(), args.workers))
    settings: dict[str, dict[str, Any]] = {}
    for job, risks in found.items():
        row, seed = row_of(job)
        settings.setdefault(row, {})[f"seed {seed}"] = settings_of(risks)
    document = {
        "run_label": "exploratory",
        "asks": "T48 thresholds fixed on the pool before the confirm run",
        "code_commit": t36.git_head(),
        "shipped_from_train_repos": SHIPPED_FROM,
        "chosen_on": "the 20 pool scoring repositories, registered option rule",
        "settings": settings,
        "wall_clock_s": time.time() - started,
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


ROLE = {cr.COUNTERS: "reference", cr.CLASSIFIER: "reference"}


def thresholds(settings: dict, row: str, seeds: Any, key: str) -> dict[int, cr.Thresholds]:
    """The pinned thresholds of one row under one option, per wiring seed."""
    return {s: cr.thresholds_of(settings[row][f"seed {s}"][key]) for s in seeds}


def confirm_traces(found: dict) -> dict[str, dict[int, dict[str, Any]]]:
    """row -> seed -> confirm repository -> traces."""
    return {
        row: {
            seed: {repo: cs.confirm_traces(repo, risks[repo]) for repo in CONFIRM}
            for seed, risks in seeds.items()
        }
        for row, seeds in cs.by_row(found).items()
    }


def option_block(
    traces: dict, settings: dict, option: Any, lay: cr.Layout
) -> tuple[list, dict, dict]:
    """Floors and the five rows (pooled and per repository), held counts, differences."""
    held = {
        row: cr.row_counts(
            traces[row], thresholds(settings, row, traces[row], option.key), option, lay
        )
        for row in cr.TIE_ORDER
    }
    rows = [
        r
        for name, c in cr.floor_counts(traces[cr.COUNTERS][0], option, lay).items()
        for r in cr.rows_of(name, "floor", c, option, lay)
    ]
    rows += [
        r
        for row in cr.TIE_ORDER
        for r in cr.rows_of(row, ROLE.get(row, "under_test"), held[row], option, lay)
    ]
    return rows, held, cr.differences(held, option, lay)


def per_seed_rows(traces: dict, settings: dict, option: Any, lay: cr.Layout) -> list:
    """Each fly and DenseNet seed on its own (reported; the seed means decide)."""
    found = []
    for row in (cr.DENSE, cr.FLY, cr.FLY_FIXED):
        for seed in traces[row]:
            at = thresholds(settings, row, [seed], option.key)
            held = cr.row_counts({seed: traces[row][seed]}, at, option, lay)
            found += cr.rows_of(f"{row} seed {seed}", "under_test", held, option, lay)[:1]
    return found


def decision(held: dict, diffs: dict, option: Any, lay: cr.Layout) -> dict[str, Any]:
    """Rule 4's verdict, the confirm call and the rule-5 lines, on the pooled primary rows."""
    benefit = {row: scored(held[row], option.value, lay.draws)[NET] for row in cr.TIE_ORDER}
    versus = {row: diffs[f"{row} minus {cr.COUNTERS}"] for row in cr.TIE_ORDER[1:]}
    live = cr.verdict(benefit, versus)
    lines = [
        f"{first} minus {second}: {d['standing']} [{d['ci95_low']:.3f}, {d['ci95_high']:.3f}]"
        for (first, second) in cr.NAMED_DIFFERENCES
        for d in [diffs[f"{first} minus {second}"]]
    ]
    return {
        "live_warner": live,
        "confirm_call": cr.confirm_call(live, benefit, diffs),
        "net_value_per_100_steps": benefit,
        "table": lines,
        "rule": (
            "best earner by point estimate; it must clear counters, "
            "else counters if they earn, else none"
        ),
    }


def report(found: dict, settings: dict) -> dict[str, Any]:
    """Every registered option's rows and differences, the per-seed rows and the verdict."""
    traces = confirm_traces(found)
    lay = cr.layout_of(traces[cr.COUNTERS][0], seed=sel.SEED, n_boot=cs.N_BOOT)
    rows, diffs, decided, seeds = [], {}, {}, []
    for option in registered_options():
        block, held, diffs[option.key] = option_block(traces, settings, option, lay)
        rows += block
        if option.key == PRIMARY:
            decided = decision(held, diffs[option.key], option, lay)
            seeds = per_seed_rows(traces, settings, option, lay)
    auc = {row: cs.auc_of(by_seed) for row, by_seed in cs.by_row(found).items()}
    return {
        "tasks": {r: len(lay.tasks[r]) for r in lay.repos},
        "verdict": decided,
        "rows": rows,
        "per_seed_rows": seeds,
        "differences": diffs,
        "roc_auc": auc,
    }


def refit_seconds(found: dict) -> dict[str, float]:
    """Wall seconds per DenseNet R2 refit on the confirm repositories."""
    times = [t for (_, _, target), r in found.items() if target != cs.POOL for t in r["refit_s"]]
    return {
        "refits": len(times),
        "mean_s": float(np.mean(times)),
        "p95_s": float(np.quantile(times, 0.95)),
        "max_s": float(np.max(times)),
    }


def score(args: argparse.Namespace) -> None:
    """The scored run: guards, ship and score, re-derive and check the thresholds, report."""
    started = time.time()
    label = run_provenance(scored=args.scored, prereg=args.prereg, expects=cs.PREREG_NAME)
    sha = cs.settings_sha(Path(args.settings), enforce=args.scored)
    settings = json.loads(Path(args.settings).read_text())["settings"]
    ra.prepare(argparse.Namespace(pool=args.pool, data_dir=args.data_dir, workers=args.workers))
    cs.prepare_confirm(Path(args.confirm_dir), args.workers)
    found = dict(g6.pool_map(cs.score_job, cs.jobs(), args.workers))
    cs.check_settings(found, settings)
    gaps = cs.t46_self_check(found, settings)
    body = report(found, settings)
    log.info("verdict: %s; %s", body["verdict"]["live_warner"], body["verdict"]["confirm_call"])
    document = {
        **label,
        "code_commit": t36.git_head(),
        "settings_sha256": sha,
        "refused_rows": dict(cs.REFUSED),
        "t46_scorer_max_gap": gaps,
        "dense_r2_refit_wall_time": refit_seconds(found),
        **body,
        "wall_clock_s": time.time() - started,
    }
    Path(args.out).write_text(json.dumps(document, indent=1))
    log.info("wrote %s (%.0fs)", args.out, time.time() - started)


def main() -> None:
    """Parse the command line and run one step."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="step", required=True)
    counting = sub.add_parser("counts")
    counting.add_argument("--confirm-dir", required=True)
    counting.add_argument("--out", required=True)
    shipping = sub.add_parser("ship")
    for name in ("pool", "data-dir", "out"):
        shipping.add_argument(f"--{name}", required=True)
    shipping.add_argument("--workers", type=int, default=8)
    scoring = sub.add_parser("score")
    for name in ("pool", "data-dir", "confirm-dir", "settings", "out"):
        scoring.add_argument(f"--{name}", required=True)
    scoring.add_argument("--scored", action="store_true")
    scoring.add_argument("--prereg")
    scoring.add_argument("--workers", type=int, default=8)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    args = parser.parse_args()
    {"counts": counts, "ship": ship, "score": score}[args.step](args)


if __name__ == "__main__":
    main()
