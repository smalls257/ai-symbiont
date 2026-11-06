"""`symbiont nightly`: train this repository's judge now, or schedule it daily.

The user says which repository and, at most, when; the model folder, trainer and judge port are
decided here from the machine and the data directory, each overridable by a named option. The
scheduler is given exactly the command typed by hand, every option pinned.
"""

import argparse
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from symbiont.service.nightly import previous_judge_url
from symbiont.service.nightly_backend import NoTrainingHardwareError
from symbiont.service.nightly_background import (
    BackgroundTools,
    KitFiles,
    build_kit,
    kit_problem,
    start_job,
    work_job,
)
from symbiont.service.nightly_job import JOB_LOG
from symbiont.service.nightly_kit import JudgeKitError
from symbiont.service.nightly_locate import (
    MODELS_FOLDER,
    ModelsNotFoundError,
    resolved_downloads,
    search_roots,
)
from symbiont.service.nightly_run import EXIT_FAILED, NightFailedError, NightPlan, run_night
from symbiont.service.nightly_schedule import (
    DEFAULT_AT,
    DailyTime,
    Platform,
    ScheduleError,
    Scheduler,
    ScheduleSpec,
    label_for,
    scheduler_for,
)
from symbiont.service.nightly_setup import KitSetupError
from symbiont.service.nightly_tools import (
    LocalMachine,
    checked_judge_python,
    default_judge_url,
    launch_detached_job,
    preflight,
    real_tools,
)

KIT_ENV = "SYMBIONT_JUDGE_KIT"
TRAINER_ENV = "SYMBIONT_TRAINER_PYTHON"
JUDGE_PYTHON_ENV = "SYMBIONT_JUDGE_PYTHON"
ACTIONS = ("install", "remove", "status")


def add_nightly_command(commands: Any, data_dir: Path) -> None:
    """Register `nightly` and `nightly schedule install|remove|status`."""
    shared = _shared_options(data_dir)
    nightly = commands.add_parser(
        "nightly",
        parents=[shared],
        help="train this repository's judge on its lessons, on this machine",
    )
    inner = nightly.add_subparsers(dest="nightly_action")
    schedule = inner.add_parser("schedule", help="run the training every day, by the OS scheduler")
    kit_help = (
        "build the judge kit from a Llama 3.2 1B Instruct folder and the downloaded kit files"
    )
    for name, helped in (
        ("setup", kit_help),
        (
            "start",
            "set up if needed, then train in the background and return (what /symbiont uses)",
        ),
        ("work", argparse.SUPPRESS),
    ):
        sub = inner.add_parser(name, parents=[shared], help=helped)
        sub.add_argument("--base", type=Path, help="folder of Llama-3.2-1B-Instruct")
        sub.add_argument("--kit-files", type=Path, help="the downloaded nightly-kit/ folder")
        sub.add_argument("--fetch-into", type=Path, help=argparse.SUPPRESS)
    actions = schedule.add_subparsers(dest="schedule_action", required=True)
    for name in ACTIONS:
        action = actions.add_parser(name, parents=[shared])
        if name == "install":
            action.add_argument("--at", default=DEFAULT_AT, help="HH:MM, 24-hour (default 03:00)")


def _shared_options(data_dir: Path) -> argparse.ArgumentParser:
    """The options every form of the command takes."""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--project", default=Path.cwd().name, help="defaults to this directory")
    shared.add_argument("--data-dir", type=Path, default=data_dir)
    shared.add_argument(
        "--kit", type=Path, help=f"judge kit folder (default ${KIT_ENV}, else DATA/judge-kit)"
    )
    shared.add_argument("--judge-url", help="loopback URL of this project's judge server")
    shared.add_argument("--trainer-python", help=f"Python with mlx-lm or torch (${TRAINER_ENV})")
    shared.add_argument(
        "--judge-python", help=f"Python the judge server runs on (${JUDGE_PYTHON_ENV})"
    )
    return shared


def run_nightly_command(
    args: argparse.Namespace,
    say: Callable[[str], None] | None = None,
    pause: Callable[[float], None] | None = None,
) -> int:
    """Dispatch: train now or in the background, build the kit, or manage the schedule.

    Lines are flushed as they are said; `pause` is how `start` waits for its job (tests inject it).
    """
    say = say or _say_now
    action = getattr(args, "nightly_action", None)
    if action == "schedule":
        return _schedule(args, say)
    if action == "setup":
        return _setup(args, say)
    if action == "start":
        return _start(args, say, pause or time.sleep)
    if action == "work":
        return _work(args)
    return _train_now(args, say)


def _say_now(line: str) -> None:
    """Print and flush, so a stage's seconds reach a log file or pipe when the stage ends."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _plan(args: argparse.Namespace) -> NightPlan:
    """The night's plan from the options, the environment and the previous record."""
    nightly_dir = args.data_dir / "nightly"
    url = args.judge_url or previous_judge_url(nightly_dir, args.project)
    return NightPlan(
        project=args.project,
        data_dir=args.data_dir,
        nightly_dir=nightly_dir,
        kit_dir=_kit_dir(args),
        judge_url=url or default_judge_url(args.project),
        trainer_python=args.trainer_python or os.environ.get(TRAINER_ENV, sys.executable),
        judge_python=_judge_python(args),
    )


def _judge_python(args: argparse.Namespace) -> str:
    """The Python the judge server runs on: the option, the variable, else this install's own."""
    return args.judge_python or os.environ.get(JUDGE_PYTHON_ENV, sys.executable)


def _kit_dir(args: argparse.Namespace) -> Path:
    """The judge kit folder: the option, the variable, else DATA/judge-kit."""
    return args.kit or Path(os.environ.get(KIT_ENV, args.data_dir / "judge-kit"))


def _train_now(args: argparse.Namespace, say: Callable[[str], None]) -> int:
    """Run one night and return its exit code; a missing machine piece is a named failure."""
    plan = _plan(args)
    judge_python = plan.judge_python
    say(f"symbiont nightly: {plan.project} (runs on this machine; nothing is uploaded)")
    try:
        checked_judge_python(judge_python)
        return run_night(plan, real_tools(say, judge_python))
    except (NoTrainingHardwareError, JudgeKitError, NightFailedError) as unready:
        say(f"symbiont nightly: FAILED: {unready}")
        return EXIT_FAILED


def schedule_argv(args: argparse.Namespace) -> tuple[str, ...]:
    """The command the scheduler runs: this same `symbiont nightly`, every option pinned."""
    plan = _plan(args)
    exe = shutil.which("symbiont")
    start = [exe] if exe else [sys.executable, "-m", "symbiont.cli"]
    judge_python = _judge_python(args)
    return (
        *start, "nightly", "--project", plan.project, "--data-dir", str(plan.data_dir),
        "--kit", str(plan.kit_dir), "--judge-url", plan.judge_url,
        "--trainer-python", plan.trainer_python, "--judge-python", judge_python,
    )  # fmt: skip


def scheduler_here() -> Scheduler:
    """The scheduler of this machine, acting on the real system."""
    getuid: Callable[[], int] = getattr(os, "getuid", lambda: 0)
    return scheduler_for(Platform.of(sys.platform), LocalMachine(), Path.home(), getuid())


def _schedule(args: argparse.Namespace, say: Callable[[str], None]) -> int:
    """install, remove or status; a scheduler failure is printed in the tool's own words."""
    label = label_for(args.project)
    try:
        scheduler = scheduler_here()
        if args.schedule_action == "install":
            return _install(args, scheduler, label, say)
        if args.schedule_action == "remove":
            scheduler.remove(label)
            say(f"removed the daily nightly run for {args.project} ({label})")
            return 0
        say(f"{args.project}: {scheduler.status(label).sentence()}")
    except ScheduleError as failed:
        say(f"symbiont nightly schedule: {failed}")
        return EXIT_FAILED
    return 0


def _install(
    args: argparse.Namespace, scheduler: Scheduler, label: str, say: Callable[[str], None]
) -> int:
    """Register the daily run and say when it will run and where its output goes."""
    log = args.data_dir / "nightly" / args.project / "schedule.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    spec = ScheduleSpec(label, DailyTime.parse(args.at), schedule_argv(args), log)
    scheduler.install(spec)
    say(f"scheduled {args.project} daily at {spec.at} ({label}); output goes to {log}")
    return 0


def _setup(args: argparse.Namespace, say: Callable[[str], None]) -> int:
    """Check the downloaded base and kit files, merge locally, and say what to do next.

    With no folders and a complete kit it only says so; with no folders and no kit it fails with
    the steps to build one.
    """
    kit_dir = _kit_dir(args)
    if kit_problem(kit_dir) is None:
        say(f"the judge kit at {kit_dir} is already complete; delete it to build it again")
        return 0
    try:
        files = _downloads(args, kit_dir)
        build_kit(kit_dir, files, _judge_python(args), say)
    except (KitSetupError, NightFailedError) as failed:
        say(f"symbiont nightly setup: FAILED: {failed}")
        return EXIT_FAILED
    say(f"the judge kit is ready at {kit_dir}; run `symbiont nightly` to train a night")
    return 0


def _start(
    args: argparse.Namespace, say: Callable[[str], None], pause: Callable[[float], None]
) -> int:
    """Train in a detached process and return once it is under way (or has ended)."""
    say(f"symbiont nightly: {args.project} (runs on this machine; nothing is uploaded)")
    tools = BackgroundTools(preflight, launch_detached_job, pause)
    plan = _plan(args)
    try:
        files = _downloads(args, plan.kit_dir)
    except ModelsNotFoundError:
        files = KitFiles(None, None, fetch_into=args.data_dir / MODELS_FOLDER)
    return start_job(plan, files, tools, say)


def _downloads(args: argparse.Namespace, kit_dir: Path) -> KitFiles:
    """The folders to build the kit from: the options, else what is on this machine."""
    roots = search_roots(os.environ, args.data_dir, Path.home())
    return resolved_downloads(KitFiles.of(args), kit_dir, roots)


def _work(args: argparse.Namespace) -> int:
    """The detached process of `start`: its output goes to the job log, its end to the job file."""
    plan = _plan(args)
    log = plan.nightly_dir / plan.project / JOB_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    return work_job(plan, KitFiles.of(args), real_tools, log)
