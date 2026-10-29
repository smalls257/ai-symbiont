"""Entry point for the Django run: checks every listed arm's endpoint before anything loads.

Phases: pilot (step-cap check on the 3 pilot ids), history (phase 1, plain), later (phase 2,
both arms). The command line contains launch.py, which the desktop watchdog keys on.
Usage: python swev_launch.py <workdir> --phase P --arm A [--arm B] --runs-dir D [--runs N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from swev_driver import PILOT, SwevDriver, phase_ids, schedule
from swev_run import Arm, Setting, endpoint
from swev_tasks import HISTORY, LATER

DEFAULT_STEP_LIMIT = 50  # dispatch: 50 unless the pilot shows Django runs need more
DEFAULT_WALL_LIMIT_MIN = 30  # the calibration's wall cap
REASONING = "low"  # the calibration's setting


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command line; the arms are listed explicitly, never implied by the phase."""
    parser = argparse.ArgumentParser(description="SWE-bench Verified Django driver")
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--phase", choices=[PILOT, HISTORY, LATER], required=True)
    parser.add_argument("--arm", type=Arm, choices=list(Arm), action="append", required=True)
    parser.add_argument("--runs", type=int, default=1, help="runs per task and arm")
    parser.add_argument("--runs-dir", required=True, help="under workdir; holds the log")
    parser.add_argument("--step-limit", type=int, default=DEFAULT_STEP_LIMIT)
    parser.add_argument("--wall-limit-min", type=int, default=DEFAULT_WALL_LIMIT_MIN)
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    for arm in args.arm:
        endpoint(arm)  # SystemExit naming the unset variable
    listed = json.loads((args.workdir / "data/swev-django-tasks.json").read_text())
    jobs = schedule(phase_ids(listed, args.phase), args.phase, args.arm, args.runs)
    setting = Setting(REASONING, args.step_limit, args.wall_limit_min * 60)
    SwevDriver(args.workdir, args.workdir / args.runs_dir, jobs, setting).run()


if __name__ == "__main__":
    main(sys.argv[1:])
