"""What each platform's scheduler is given for a daily nightly run, and what it reports back.

Violation prevented: Distributed Monolith. The scheduler string and the command it wakes must
agree; these tests read the exact plist, crontab line and schtasks arguments. A fake system stands
in for launchctl, crontab and schtasks, so no real scheduler is called.
"""

import plistlib
from pathlib import Path

import pytest

from symbiont.service.nightly_schedule import (
    Completed,
    DailyTime,
    LinuxScheduler,
    MacScheduler,
    Platform,
    ScheduleError,
    ScheduleSpec,
    WindowsScheduler,
    crontab_line,
    crontab_time,
    crontab_with,
    label_for,
    launchd_plist,
    launchd_time,
    scheduler_for,
    schtasks_create,
    schtasks_time,
)

HOME = Path("/h")
SPEC = ScheduleSpec(
    "com.symbiont.nightly.demo",
    DailyTime(3, 5),
    ("/usr/local/bin/symbiont", "nightly", "--project", "my demo"),
    Path("/data/nightly/demo/schedule.log"),
)


class FakeSystem:
    """Records every call; `answers` maps the first argv words to a Completed."""

    def __init__(self, answers=None, files=None):
        self.calls, self.stdins = [], []
        self.answers = answers or {}
        self.files = dict(files or {})

    def run(self, tool, args, stdin=None):
        argv = [tool.value, *args]
        self.calls.append(argv)
        self.stdins.append(stdin)
        for prefix, done in self.answers.items():
            if " ".join(argv).startswith(prefix):
                return done
        return Completed(0, "")

    def write(self, path, data):
        self.files[path] = data

    def delete(self, path):
        self.files.pop(path, None)

    def read(self, path):
        return self.files.get(path)


def test_daily_time_parses_hh_mm_and_refuses_everything_else():
    assert str(DailyTime.parse("3:05")) == "03:05"
    assert DailyTime.parse("23:59") == DailyTime(23, 59)
    for bad in ("24:00", "3", "03:60", "noon", ""):
        with pytest.raises(ScheduleError, match="HH:MM"):
            DailyTime.parse(bad)


def test_platform_comes_from_sys_platform_and_an_unknown_system_raises():
    assert Platform.of("darwin") is Platform.MACOS
    assert Platform.of("linux") is Platform.LINUX
    assert Platform.of("win32") is Platform.WINDOWS
    with pytest.raises(ScheduleError, match="freebsd"):
        Platform.of("freebsd14")


def test_the_label_is_safe_for_every_scheduler():
    assert label_for("owner/my repo") == "com.symbiont.nightly.owner-my-repo"


def test_the_launchd_plist_runs_the_command_daily_and_logs_to_the_file():
    document = plistlib.loads(launchd_plist(SPEC))
    assert document["Label"] == SPEC.label
    assert document["ProgramArguments"] == list(SPEC.argv)
    assert document["StartCalendarInterval"] == {"Hour": 3, "Minute": 5}
    assert document["StandardOutPath"] == document["StandardErrorPath"] == str(SPEC.log)
    assert launchd_time(launchd_plist(SPEC)) == DailyTime(3, 5)


def test_macos_install_writes_the_plist_then_bootstraps_it_in_the_users_gui_domain():
    system = FakeSystem({"launchctl print": Completed(113, "not found")})
    MacScheduler(system, HOME, 501).install(SPEC)
    plist = HOME / "Library" / "LaunchAgents" / "com.symbiont.nightly.demo.plist"
    assert plist in system.files
    assert system.calls[-1] == ["launchctl", "bootstrap", "gui/501", str(plist)]
    assert not any("bootout" in call for call in system.calls)


def test_macos_install_replaces_a_loaded_agent_with_bootout_first():
    system = FakeSystem()
    MacScheduler(system, HOME, 501).install(SPEC)
    verbs = [call[1] for call in system.calls]
    assert verbs == ["print", "bootout", "bootstrap"]


def test_macos_remove_unloads_and_deletes_the_plist():
    system = FakeSystem()
    scheduler = MacScheduler(system, HOME, 501)
    scheduler.install(SPEC)
    scheduler.remove(SPEC.label)
    assert system.files == {}
    assert ["launchctl", "bootout", "gui/501/com.symbiont.nightly.demo"] in system.calls


def test_macos_status_needs_both_the_plist_and_a_loaded_agent():
    plist = HOME / "Library" / "LaunchAgents" / "com.symbiont.nightly.demo.plist"
    loaded = MacScheduler(FakeSystem(files={plist: launchd_plist(SPEC)}), HOME, 501)
    assert loaded.status(SPEC.label).at == DailyTime(3, 5)
    unloaded = FakeSystem({"launchctl print": Completed(113, "")}, {plist: launchd_plist(SPEC)})
    assert not MacScheduler(unloaded, HOME, 501).status(SPEC.label).installed


def test_a_failing_bootstrap_raises_with_the_tools_own_words():
    system = FakeSystem(
        {
            "launchctl print": Completed(113, ""),
            "launchctl bootstrap": Completed(5, "Bootstrap failed: 5"),
        }
    )
    with pytest.raises(ScheduleError, match="Bootstrap failed: 5"):
        MacScheduler(system, HOME, 501).install(SPEC)


def test_the_crontab_line_is_daily_quoted_logged_and_tagged():
    line = crontab_line(SPEC)
    assert line == (
        "5 3 * * * /usr/local/bin/symbiont nightly --project 'my demo' "
        ">> /data/nightly/demo/schedule.log 2>&1  # symbiont-nightly:com.symbiont.nightly.demo"
    )
    assert crontab_time(line, SPEC.label) == DailyTime(3, 5)


def test_crontab_install_keeps_other_jobs_and_replaces_this_projects_old_line():
    other = "0 1 * * * backup.sh"
    old = crontab_line(ScheduleSpec(SPEC.label, DailyTime(9, 9), SPEC.argv, SPEC.log))
    text = crontab_with(f"{other}\n{old}\n", SPEC)
    assert text.splitlines()[0] == other
    assert text.count("symbiont-nightly") == 1
    assert "5 3 * * *" in text


def test_linux_install_with_no_crontab_yet_writes_just_our_line():
    system = FakeSystem({"crontab -l": Completed(1, "no crontab for me")})
    LinuxScheduler(system).install(SPEC)
    assert system.calls[-1] == ["crontab", "-"]
    assert system.stdins[-1] == crontab_line(SPEC) + "\n"


def test_linux_remove_leaves_other_jobs_and_status_reports_the_time():
    existing = f"0 1 * * * backup.sh\n{crontab_line(SPEC)}\n"
    system = FakeSystem({"crontab -l": Completed(0, existing)})
    scheduler = LinuxScheduler(system)
    assert scheduler.status(SPEC.label).at == DailyTime(3, 5)
    scheduler.remove(SPEC.label)
    assert system.stdins[-1] == "0 1 * * * backup.sh\n"


def test_a_crontab_read_that_fails_for_another_reason_raises():
    with pytest.raises(ScheduleError, match="permission"):
        LinuxScheduler(FakeSystem({"crontab -l": Completed(1, "permission denied")})).status("x")


def test_schtasks_create_is_daily_at_the_time_and_replaces_by_name():
    assert schtasks_create(SPEC) == [
        "/Create", "/F", "/SC", "DAILY", "/TN", SPEC.label, "/ST", "03:05",
        "/TR", '/usr/local/bin/symbiont nightly --project "my demo"',
    ]  # fmt: skip


def test_windows_status_reads_the_start_time_and_remove_deletes_only_an_existing_task():
    query = "TaskName: x\nStart Time:   3:05:00 AM\n"
    system = FakeSystem({"schtasks /Query": Completed(0, query)})
    scheduler = WindowsScheduler(system)
    assert scheduler.status(SPEC.label).at == DailyTime(3, 5)
    scheduler.remove(SPEC.label)
    assert ["schtasks", "/Delete", "/F", "/TN", SPEC.label] in system.calls
    absent = FakeSystem({"schtasks /Query": Completed(1, "ERROR: not found")})
    WindowsScheduler(absent).remove(SPEC.label)
    assert all(call[1] != "/Delete" for call in absent.calls)
    assert schtasks_time("no time here") is None


def test_scheduler_for_picks_the_class_of_the_platform():
    system = FakeSystem()
    assert isinstance(scheduler_for(Platform.MACOS, system, Path("/h"), 1), MacScheduler)
    assert isinstance(scheduler_for(Platform.LINUX, system, Path("/h"), 1), LinuxScheduler)
    assert isinstance(scheduler_for(Platform.WINDOWS, system, Path("/h"), 1), WindowsScheduler)
