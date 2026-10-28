"""T48 confirm run on tox, dask and PyBaMM: counts, then the settings shipped from the pool.

prereg/2026-10-28-confirm-DRAFT.md describes the run. Nothing is fit on the confirm
repositories: every learner is shipped from the 80 T47 pool training repositories, and every
note threshold is chosen by the registered option A rule on the 20 pool scoring repositories
(the T47 N = 80 setting), then fixed.

    run_confirm_scored.py counts --confirm-dir data/nebius-openhands/confirm \
        --out data/t48-counts.json
    run_confirm_scored.py ship --pool results/repo-pool.json --data-dir data/nebius-openhands/pool \
        --out results/confirm-shipped-settings.json --workers 10

`counts` reads the confirm files through the OpenHands reader and prints counts only: refused
rows, tasks, sessions, steps. `ship` reads the pool only. Set OMP_NUM_THREADS=1.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import run_fly_ablation as ra
import run_penalized as t36
import run_repo_curve as rc
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.note_cost_scored_report import registered_options, train_stack
from symbiont.eval.offline import drop_taskless
from symbiont.readers import openhands
from symbiont.readers.errors import ReadError

log = logging.getLogger("confirm")
CONFIRM = ("tox-dev/tox", "dask/dask", "pybamm-team/PyBaMM")
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


def settings_of(risks: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Each registered option's (note, warning) thresholds chosen on the pool scoring traces."""
    traces = rc.traces_of(risks)
    found = {}
    for option in registered_options():
        stack = train_stack(traces, option)
        index, score = option.choose(stack.counts)
        note, warn = stack.settings[index]
        found[option.key] = {
            "note_at_or_above": _finite(note),
            "warning_at_or_above": _finite(warn),
            "pool_score": score,
        }
    return found


def _finite(threshold: float) -> float | None:
    """A threshold, or None for a tier that never speaks (strict JSON has no Infinity)."""
    return None if threshold == float("inf") else threshold


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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    args = parser.parse_args()
    {"counts": counts, "ship": ship}[args.step](args)


if __name__ == "__main__":
    main()
