"""`symbiont nightly` as typed: options, defaults, the scheduled command, and exit codes.

Violation prevented: Leaky Narrative at the command line. The scheduled command is exactly the
manual one, every option pinned; the trainer and the scheduler are fakes, so nothing real runs.
"""

import sys
from pathlib import Path

import pytest

from nightly_support import FakeNight
from symbiont import cli
from symbiont.service import nightly_command
from symbiont.service.nightly import NightlyRecord, write_record
from symbiont.service.nightly_backend import Backend, NoTrainingHardwareError
from symbiont.service.nightly_schedule import ScheduleError, ScheduleStatus

pytestmark = pytest.mark.periphery


class FakeScheduler:
    def __init__(self, installed=None, fail=False):
        self.calls, self.fail = [], fail
        self.installed = installed

    def install(self, spec):
        if self.fail:
            raise ScheduleError("launchctl bootstrap failed (exit 5): nope")
        self.calls.append(("install", spec))

    def remove(self, label):
        self.calls.append(("remove", label))

    def status(self, label):
        self.calls.append(("status", label))
        return self.installed or ScheduleStatus(installed=False)


def store_option(path):
    return ("--data-dir", str(path))


def parse(*argv):
    return cli._parser().parse_args(["nightly", *argv])


def run(args, said_lines):
    return nightly_command.run_nightly_command(args, said_lines.append)


def test_the_project_defaults_to_this_directory_and_the_data_dir_to_the_users_symbiont(tmp_path):
    args = parse()
    assert args.project == Path.cwd().name
    assert args.nightly_action is None
    assert args.data_dir == cli.DEFAULT_DATA_DIR


def test_nightly_trains_with_the_options_it_was_given(tmp_path, monkeypatch):
    night = FakeNight(Backend.MLX)
    monkeypatch.setattr(nightly_command, "real_tools", lambda say, judge_python: night.tools())
    monkeypatch.setattr(nightly_command, "checked_judge_python", lambda python: None)
    seen = {}
    monkeypatch.setattr(
        nightly_command, "run_night", lambda plan, tools: seen.setdefault("plan", plan) and 0
    )
    lines = []
    args = parse(
        "--project",
        "p",
        "--data-dir",
        str(tmp_path),
        "--kit",
        "/k",
        "--judge-url",
        "http://127.0.0.1:9",
        "--trainer-python",
        "/py",
    )
    assert run(args, lines) == 0
    plan = seen["plan"]
    assert (plan.project, plan.kit_dir, plan.judge_url, plan.trainer_python) == (
        "p",
        Path("/k"),
        "http://127.0.0.1:9",
        "/py",
    )
    assert plan.nightly_dir == tmp_path / "nightly"
    assert "nothing is uploaded" in lines[0]


def test_the_judge_url_defaults_to_the_last_records_then_to_the_projects_own_port(tmp_path):
    before = nightly_command._plan(parse("--project", "p", *store_option(tmp_path)))
    assert before.judge_url.startswith("http://127.0.0.1:88")
    write_record(
        tmp_path / "nightly", "p", NightlyRecord("d", "http://127.0.0.1:8999", 1, "t", "mlx")
    )
    after = nightly_command._plan(parse("--project", "p", *store_option(tmp_path)))
    assert after.judge_url == "http://127.0.0.1:8999"


def test_the_kit_comes_from_the_option_then_the_environment_then_the_data_dir(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("SYMBIONT_JUDGE_KIT", raising=False)
    plain = nightly_command._plan(parse(*store_option(tmp_path)))
    assert plain.kit_dir == tmp_path / "judge-kit"
    monkeypatch.setenv("SYMBIONT_JUDGE_KIT", "/from/env")
    assert nightly_command._plan(parse(*store_option(tmp_path))).kit_dir == Path("/from/env")


def test_a_machine_with_no_accelerator_exits_nonzero_with_the_reason(tmp_path, monkeypatch):
    def refuse(say, judge_python):
        raise NoTrainingHardwareError("no accelerator to train on (Linux x86_64)")

    monkeypatch.setattr(nightly_command, "real_tools", refuse)
    monkeypatch.setattr(nightly_command, "checked_judge_python", lambda python: None)
    lines = []
    assert run(parse(*store_option(tmp_path)), lines) == 1
    assert "no accelerator" in lines[-1]


def test_the_scheduled_command_is_the_manual_one_with_every_option_pinned(tmp_path):
    args = parse(
        "schedule", "install", "--project", "p", *store_option(tmp_path), "--kit", str(Path("/k")),
        "--trainer-python", "/py", "--judge-python", "/jpy",
    )  # fmt: skip
    argv = nightly_command.schedule_argv(args)
    assert argv[argv.index("nightly") :] == (
        "nightly", "--project", "p", *store_option(tmp_path), "--kit", str(Path("/k")),
        "--judge-url", nightly_command.default_judge_url("p"),
        "--trainer-python", "/py", "--judge-python", "/jpy",
    )  # fmt: skip
    assert argv[0] == sys.executable or Path(argv[0]).stem.lower() == "symbiont"


def test_install_registers_the_daily_run_and_says_when_and_where_the_log_is(tmp_path, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(nightly_command, "scheduler_here", lambda: scheduler)
    lines = []
    args = parse("schedule", "install", "--project", "p", *store_option(tmp_path), "--at", "04:30")
    assert run(args, lines) == 0
    ((verb, spec),) = scheduler.calls
    assert (verb, str(spec.at), spec.label) == ("install", "04:30", "com.symbiont.nightly.p")
    assert spec.log == tmp_path / "nightly" / "p" / "schedule.log" and spec.log.parent.is_dir()
    assert "daily at 04:30" in lines[0]


def test_install_defaults_to_three_in_the_morning(tmp_path, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(nightly_command, "scheduler_here", lambda: scheduler)
    run(parse("schedule", "install", *store_option(tmp_path)), [])
    assert str(scheduler.calls[0][1].at) == "03:00"


def test_a_bad_time_fails_loudly_and_installs_nothing(tmp_path, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(nightly_command, "scheduler_here", lambda: scheduler)
    lines = []
    assert run(parse("schedule", "install", *store_option(tmp_path), "--at", "25:00"), lines) == 1
    assert "HH:MM" in lines[-1] and scheduler.calls == []


def test_a_scheduler_failure_is_printed_in_its_own_words_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly_command, "scheduler_here", lambda: FakeScheduler(fail=True))
    lines = []
    assert run(parse("schedule", "install", *store_option(tmp_path)), lines) == 1
    assert "bootstrap failed (exit 5)" in lines[-1]


def test_remove_and_status_speak_for_the_project(tmp_path, monkeypatch):
    scheduler = FakeScheduler(installed=ScheduleStatus(installed=False))
    monkeypatch.setattr(nightly_command, "scheduler_here", lambda: scheduler)
    lines = []
    assert run(parse("schedule", "remove", "--project", "p", *store_option(tmp_path)), lines) == 0
    assert run(parse("schedule", "status", "--project", "p", *store_option(tmp_path)), lines) == 0
    assert "removed" in lines[0] and lines[1] == "p: no daily nightly run is scheduled"
    assert [c[0] for c in scheduler.calls] == ["remove", "status"]


def test_the_cli_routes_nightly_to_this_command(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_nightly_command", lambda args, **_: 42)
    assert cli.main(["nightly", *store_option(tmp_path)]) == 42


def test_lines_reach_stdout_as_they_are_said(capsys):
    nightly_command._say_now("  train: 1.0s")
    assert capsys.readouterr().out == "  train: 1.0s\n"


def test_the_judge_and_trainer_default_to_the_python_this_install_runs_on(tmp_path, monkeypatch):
    monkeypatch.delenv("SYMBIONT_JUDGE_PYTHON", raising=False)
    monkeypatch.delenv("SYMBIONT_TRAINER_PYTHON", raising=False)
    plan = nightly_command._plan(parse("--project", "p", *store_option(tmp_path)))
    assert plan.judge_python == plan.trainer_python == sys.executable


def test_setup_with_no_folders_and_no_kit_fails_with_the_steps(tmp_path):
    lines = []
    args = parse("setup", "--kit", str(tmp_path / "none"), *store_option(tmp_path))
    assert run(args, lines) == 1
    assert "huggingface-cli download" in lines[0] and "symbiont nightly setup" in lines[0]


def test_setup_with_no_folders_reuses_a_complete_kit(tmp_path):
    from nightly_support import write_kit

    write_kit(tmp_path / "kit")
    lines = []
    assert run(parse("setup", "--kit", str(tmp_path / "kit"), *store_option(tmp_path)), lines) == 0
    assert "already complete" in lines[0]


def test_start_with_no_lessons_says_so_and_exits_2_without_launching(tmp_path, monkeypatch):
    from nightly_support import write_kit

    write_kit(tmp_path / "kit")
    monkeypatch.setattr(nightly_command, "preflight", lambda plan: None)
    launched = []
    monkeypatch.setattr(nightly_command, "launch_detached_job", lambda *a: launched.append(a))
    args = parse("start", "--kit", str(tmp_path / "kit"), *store_option(tmp_path))
    lines = []
    assert nightly_command.run_nightly_command(args, lines.append, lambda seconds: None) == 2
    assert launched == [] and "mine" in lines[-1]
