"""`nightly start` and its detached `work`: fail fast, launch once, always leave a final state.

Violation prevented: Silent Fallback. A missing kit, no lessons, no accelerator and a missing
package each end the call loudly before anything is launched; a crashed job still writes FAILED.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from nightly_support import PROJECT, FakeNight
from nightly_support import night_plan as setup
from symbiont.service.nightly_backend import Backend, NoTrainingHardwareError
from symbiont.service.nightly_background import (
    BackgroundTools,
    KitFiles,
    start_job,
    work_args,
    work_job,
)
from symbiont.service.nightly_job import JobPhase, JobState, read_job, utc_now, write_job
from symbiont.service.nightly_run import EXIT_FAILED, EXIT_NO_LESSONS, NightFailedError

pytestmark = pytest.mark.periphery
NONE = KitFiles(None, None)


class Launches:
    def __init__(self):
        self.calls = []

    def __call__(self, python, args, log):
        assert python
        self.calls.append((list(args), log))


def tools(launch, preflight=lambda plan: None, pause=lambda seconds: None):
    return BackgroundTools(preflight, launch, pause)


def test_start_launches_once_and_says_how_to_check(tmp_path):
    plan, launch, said = setup(tmp_path, lessons=4), Launches(), []
    assert start_job(plan, NONE, tools(launch), said.append, watch_s=4.0) == 0
    assert said == ["training started; 4 lessons; check with `/symbiont status`"]
    ((argv, log),) = launch.calls
    assert argv[:4] == ["-m", "symbiont.cli", "nightly", "work"]
    assert log == plan.nightly_dir / PROJECT / "job.log"
    state = read_job(plan.nightly_dir, PROJECT)
    assert state is not None and state.phase is JobPhase.RUNNING and state.lessons == 4


def test_a_second_start_while_one_runs_launches_nothing(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []
    write_job(plan.nightly_dir, PROJECT, JobState(JobPhase.RUNNING, utc_now(), 6))
    assert start_job(plan, NONE, tools(launch), said.append) == 0
    assert launch.calls == [] and "already running" in said[0]


def test_a_job_that_ends_while_we_watch_is_reported_as_done(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []

    def finish(seconds):
        write_job(plan.nightly_dir, PROJECT, JobState(JobPhase.DONE, utc_now(), 6, "T"))

    assert start_job(plan, NONE, tools(launch, pause=finish), said.append) == 0
    assert said == ["training done: 6 lessons at T; the checker is live"]


def test_a_job_that_fails_while_we_watch_exits_nonzero_with_the_reason(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []

    def fail(seconds):
        write_job(plan.nightly_dir, PROJECT, JobState(JobPhase.FAILED, utc_now(), 6, "T", "boom"))

    assert start_job(plan, NONE, tools(launch, pause=fail), said.append) == EXIT_FAILED
    assert said == ["symbiont nightly: FAILED: boom"]


def test_a_spent_time_budget_still_says_training_started(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []

    def out_of_time(seconds):
        raise KeyboardInterrupt

    assert start_job(plan, NONE, tools(launch, pause=out_of_time), said.append) == 0
    assert said[-1].startswith("training started; 6 lessons")


def test_no_kit_and_no_folders_fails_with_the_exact_steps_and_launches_nothing(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []
    plan = plan.__class__(**{**plan.__dict__, "kit_dir": tmp_path / "no-kit"})
    assert start_job(plan, NONE, tools(launch), said.append) == EXIT_FAILED
    assert launch.calls == []
    for step in ("huggingface-cli login", "huggingface-cli download", "symbiont nightly setup"):
        assert step in said[0]


def test_folders_that_are_not_a_base_and_kit_fail_before_any_launch(tmp_path):
    plan, launch, said = setup(tmp_path), Launches(), []
    plan = plan.__class__(**{**plan.__dict__, "kit_dir": tmp_path / "no-kit"})
    wrong = KitFiles(tmp_path / "base", tmp_path / "kit")
    assert start_job(plan, wrong, tools(launch), said.append) == EXIT_FAILED
    assert launch.calls == [] and "FAILED" in said[0]


def test_no_lessons_exits_2_and_launches_nothing(tmp_path):
    plan, launch, said = setup(tmp_path, lessons=0), Launches(), []
    assert start_job(plan, NONE, tools(launch), said.append) == EXIT_NO_LESSONS
    assert launch.calls == [] and read_job(plan.nightly_dir, PROJECT) is None


@pytest.mark.parametrize(
    "problem",
    [
        NightFailedError("this install lacks the nightly packages"),
        NoTrainingHardwareError("no accelerator"),
    ],
)
def test_a_machine_that_cannot_train_fails_before_launching(tmp_path, problem):
    plan, launch, said = setup(tmp_path), Launches(), []

    def refuse(plan):
        raise problem

    assert start_job(plan, NONE, tools(launch, preflight=refuse), said.append) == EXIT_FAILED
    assert launch.calls == [] and str(problem) in said[0]


def test_the_detached_command_pins_the_options_and_carries_the_folders(tmp_path):
    plan = setup(tmp_path)
    argv = work_args(plan, KitFiles(Path("/b"), Path("/k")))
    assert argv[argv.index("--project") + 1] == PROJECT
    assert argv[argv.index("--base") + 1] == str(Path("/b")) and argv[
        argv.index("--kit-files") + 1
    ] == str(Path("/k"))
    assert "--base" not in work_args(plan, NONE)


def make_work(tmp_path, night):
    plan = setup(tmp_path)
    write_job(plan.nightly_dir, PROJECT, JobState(JobPhase.RUNNING, "S", 6))
    log = plan.nightly_dir / PROJECT / "job.log"
    return plan, log, lambda say, python: replace(night.tools(), say=say)


def test_work_trains_and_leaves_done_with_the_lessons(tmp_path):
    plan, log, make = make_work(tmp_path, FakeNight(Backend.MLX))
    assert work_job(plan, NONE, make, log) == 0
    state = read_job(plan.nightly_dir, PROJECT)
    assert state is not None and state.phase is JobPhase.DONE and state.lessons == 6
    assert state.started == "S"
    assert "trained on 6 lessons" in log.read_text(encoding="utf-8")


def test_work_that_fails_leaves_failed_with_the_trainers_reason(tmp_path):
    plan, log, make = make_work(tmp_path, FakeNight(Backend.MLX, exit_code=1))
    assert work_job(plan, NONE, make, log) == EXIT_FAILED
    state = read_job(plan.nightly_dir, PROJECT)
    assert state is not None and state.phase is JobPhase.FAILED
    assert "the trainer exited 1" in state.reason


def test_work_that_crashes_still_leaves_failed_and_reraises(tmp_path):
    plan, log, _ = make_work(tmp_path, FakeNight(Backend.MLX))

    def explode(say, python):
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        work_job(plan, NONE, explode, log)
    state = read_job(plan.nightly_dir, PROJECT)
    assert state is not None and state.phase is JobPhase.FAILED and "kaboom" in state.reason
