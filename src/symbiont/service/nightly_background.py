"""`symbiont nightly start`: build the kit if needed, then train in a detached process.

A tool call must return in under a minute and the training takes 1-4, so `start` checks everything
that can fail fast (kit, lessons, hardware, packages), launches `symbiont nightly work` detached and
watches its job file for a bounded time. `work` is that detached process: it builds the kit if
needed, runs the night and always leaves a final job state, so `symbiont status` never guesses.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from symbiont.service.nightly_backend import NoTrainingHardwareError
from symbiont.service.nightly_bundle import routea_dir
from symbiont.service.nightly_job import (
    JOB_LOG,
    STALE_AFTER_S,
    JobPhase,
    JobState,
    read_job,
    utc_now,
    write_job,
)
from symbiont.service.nightly_kit import JudgeKitError, open_kit
from symbiont.service.nightly_run import (
    EXIT_FAILED,
    EXIT_NO_LESSONS,
    NightFailedError,
    NightPlan,
    NightTools,
    NoLessonsError,
    Say,
    lesson_count,
    run_night,
)
from symbiont.service.nightly_setup import (
    SETUP_STEPS,
    KitSetupError,
    SetupInputs,
    check_base,
    check_kit_files,
    check_merge_python,
    merge_kit,
)
from symbiont.service.nightly_tools import run_logged

MERGE_SCRIPT = "merge_adapter_torch.py"
# A tool call is bounded (the MCP client times out near a minute); `repo mine` follows 45 s too.
WATCH_S = 45.0
POLL_S = 2.0

Launch = Callable[[str, Sequence[str], Path], None]
Preflight = Callable[[NightPlan], None]


@dataclass(frozen=True)
class KitFiles:
    """The downloaded base and kit folders that `setup` merges; both None when none were given."""

    base: Path | None
    kit_files: Path | None

    @staticmethod
    def of(args: argparse.Namespace) -> "KitFiles":
        """The `--base` and `--kit-files` options (absent options read as None)."""
        return KitFiles(getattr(args, "base", None), getattr(args, "kit_files", None))


@dataclass(frozen=True)
class BackgroundTools:
    """The machine `start` touches: the pre-flight checks, the detached launch and the pause."""

    preflight: Preflight
    launch: Launch
    pause: Callable[[float], None]


def kit_problem(kit_dir: Path) -> str | None:
    """Why the kit at `kit_dir` is not usable, or None when it is complete."""
    try:
        open_kit(kit_dir)
    except JudgeKitError as incomplete:
        return str(incomplete)
    return None


def checked_kit_request(kit_dir: Path, files: KitFiles) -> None:
    """Return when the kit is complete or `files` can build it; else raise KitSetupError.

    Checked before any merge or training, so a wrong folder costs seconds, not minutes.
    """
    problem = kit_problem(kit_dir)
    if problem is None:
        return
    if files.base is None or files.kit_files is None:
        raise KitSetupError(f"no judge kit at {kit_dir} ({problem}); {SETUP_STEPS}")
    check_base(files.base)
    check_kit_files(files.kit_files)


def build_kit(kit_dir: Path, files: KitFiles, merge_python: str, say: Say) -> None:
    """Merge the downloaded folders into `kit_dir`; raises KitSetupError or NightFailedError."""
    if files.base is None or files.kit_files is None:
        raise KitSetupError(f"no judge kit at {kit_dir}; {SETUP_STEPS}")
    check_base(files.base)
    check_kit_files(files.kit_files)
    script = routea_dir() / MERGE_SCRIPT
    if not script.is_file():
        raise KitSetupError(f"{MERGE_SCRIPT} is not in {script.parent}; reinstall ai-symbiont")
    kit_dir.mkdir(parents=True, exist_ok=True)
    check_merge_python(merge_python, run_logged, kit_dir / "setup-python.log")
    say("base and kit files check out; merging locally (nothing is uploaded or downloaded)")
    merge_kit(
        SetupInputs(files.base, files.kit_files, kit_dir, merge_python), run_logged, script, say
    )


def start_job(
    plan: NightPlan, files: KitFiles, tools: BackgroundTools, say: Say, watch_s: float = WATCH_S
) -> int:
    """Check, launch the detached training, report within `watch_s`; returns an exit code.

    0 running or done, EXIT_NO_LESSONS with nothing to train on, else EXIT_FAILED.
    """
    running = _running_job(plan, say)
    if running is not None:
        say(f"training is already running since {running.started}; check with `/symbiont status`")
        return 0
    try:
        checked_kit_request(plan.kit_dir, files)
        count = lesson_count(plan)
        tools.preflight(plan)
    except NoLessonsError as nothing:
        say(f"symbiont nightly: {nothing}")
        return EXIT_NO_LESSONS
    except (KitSetupError, NightFailedError, JudgeKitError, NoTrainingHardwareError) as unready:
        say(f"symbiont nightly: FAILED: {unready}")
        return EXIT_FAILED
    write_job(plan.nightly_dir, plan.project, JobState(JobPhase.RUNNING, utc_now(), count))
    log = plan.nightly_dir / plan.project / JOB_LOG
    tools.launch(sys.executable, work_args(plan, files), log)
    return _report_after_watch(plan, count, tools, say, watch_s)


def _running_job(plan: NightPlan, say: Say) -> JobState | None:
    """The job running now, or None (none, finished, too old to be alive, or an unusable file)."""
    try:
        state = read_job(plan.nightly_dir, plan.project)
    except ValueError as unusable:
        say(f"symbiont nightly: {unusable}; starting a new job over it")
        return None
    if state is None or state.phase is not JobPhase.RUNNING:
        return None
    age = (datetime.now(UTC) - datetime.fromisoformat(state.started)).total_seconds()
    return state if age <= STALE_AFTER_S else None


def work_args(plan: NightPlan, files: KitFiles) -> list[str]:
    """The detached process's arguments after `python`: `symbiont nightly work`, options pinned."""
    argv = [
        "-m", "symbiont.cli", "nightly", "work",
        "--project", plan.project, "--data-dir", str(plan.data_dir), "--kit", str(plan.kit_dir),
        "--judge-url", plan.judge_url, "--trainer-python", plan.trainer_python,
        "--judge-python", plan.judge_python,
    ]  # fmt: skip
    if files.base is not None and files.kit_files is not None:
        argv += ["--base", str(files.base), "--kit-files", str(files.kit_files)]
    return argv


def _report_after_watch(
    plan: NightPlan, count: int, tools: BackgroundTools, say: Say, watch_s: float
) -> int:
    """Follow the job file for `watch_s`; say it started, or how it ended."""
    started = f"training started; {count} lessons; check with `/symbiont status`"
    try:
        for _ in range(int(watch_s / POLL_S)):
            tools.pause(POLL_S)
            ended = _ended_job(plan)
            if ended is not None:
                return _say_ended(ended, say)
    except KeyboardInterrupt:
        say(started)  # the caller's time budget is spent; the job goes on, which is the answer
        return 0
    say(started)
    return 0


def _ended_job(plan: NightPlan) -> JobState | None:
    """The job's final state, or None while it runs."""
    state = read_job(plan.nightly_dir, plan.project)
    return None if state is None or state.phase is JobPhase.RUNNING else state


def _say_ended(state: JobState, say: Say) -> int:
    """The end of a job that finished while we watched."""
    if state.phase is JobPhase.DONE:
        say(f"training done: {state.lessons} lessons at {state.finished}; the checker is live")
        return 0
    say(f"symbiont nightly: FAILED: {state.reason}")
    return EXIT_FAILED


def work_job(
    plan: NightPlan, files: KitFiles, make_tools: Callable[[Say, str], NightTools], log: Path
) -> int:
    """The detached process: build the kit if needed, train, and always leave a final job state."""
    lines: list[str] = []
    began = read_job(plan.nightly_dir, plan.project)
    started = began.started if began else utc_now()
    count = began.lessons if began else None
    with log.open("a", encoding="utf-8") as sink:

        def say(line: str) -> None:
            lines.append(line)
            sink.write(line + "\n")
            sink.flush()

        try:
            if kit_problem(plan.kit_dir) is not None:
                build_kit(plan.kit_dir, files, plan.judge_python, say)
            code = run_night(plan, make_tools(say, plan.judge_python))
        except (KitSetupError, NightFailedError, JudgeKitError, NoTrainingHardwareError) as failed:
            say(f"symbiont nightly: FAILED: {failed}")
            code = EXIT_FAILED
        except Exception as crashed:
            _finish(plan, JobState(JobPhase.FAILED, started, count, utc_now(), repr(crashed)))
            raise
    _finish(plan, _final_state(code, lines, started, count))
    return code


def _final_state(code: int, lines: list[str], started: str, count: int | None) -> JobState:
    """DONE for exit 0; else FAILED with the last `symbiont nightly:` line as the reason."""
    if code == 0:
        return JobState(JobPhase.DONE, started, count, utc_now())
    said = [line for line in lines if line.startswith("symbiont nightly:")]
    last = said[-1] if said else ""
    reason = last.removeprefix("symbiont nightly:").removeprefix(" FAILED:").strip()
    return JobState(JobPhase.FAILED, started, count, utc_now(), reason or f"exit {code}")


def _finish(plan: NightPlan, state: JobState) -> None:
    """Write the final state."""
    write_job(plan.nightly_dir, plan.project, state)
