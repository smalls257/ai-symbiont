"""A daily `symbiont nightly` run in the operating system's own scheduler.

macOS gets a user LaunchAgent, Linux a tagged line in the user's crontab, Windows a Task Scheduler
task, chosen by the `Platform` enum. Each platform's text is built by a pure function; the tools
are called through `SchedulerSystem`, so tests call no real scheduler. A failed call raises.
"""

import plistlib
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

DEFAULT_AT = "03:00"
TAG = "# symbiont-nightly:"
LABEL_PREFIX = "com.symbiont.nightly."
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class Tool(StrEnum):
    """The scheduler programs this module talks to, one per platform."""

    LAUNCHCTL = "launchctl"
    CRONTAB = "crontab"
    SCHTASKS = "schtasks"


class Platform(StrEnum):
    """Which scheduler this machine has."""

    MACOS = "macos"
    LINUX = "linux"
    WINDOWS = "windows"

    @classmethod
    def of(cls, sys_platform: str) -> "Platform":
        """The platform for `sys.platform`. Raises ScheduleError for any other system."""
        if sys_platform == "darwin":
            return cls.MACOS
        if sys_platform.startswith("linux"):
            return cls.LINUX
        if sys_platform == "win32":
            return cls.WINDOWS
        raise ScheduleError(
            f"no scheduler is known for {sys_platform}; run `symbiont nightly` by hand"
        )


class ScheduleError(RuntimeError):
    """The schedule could not be changed or read; the message carries the tool's own words."""


@dataclass(frozen=True)
class DailyTime:
    """A time of day, 24-hour clock."""

    hour: int
    minute: int

    @classmethod
    def parse(cls, text: str) -> "DailyTime":
        """`HH:MM`. Raises ScheduleError for anything else."""
        found = _TIME.match(text.strip())
        if found is None:
            raise ScheduleError(f"--at wants a 24-hour HH:MM time such as 03:00, not {text!r}")
        return cls(int(found.group(1)), int(found.group(2)))

    def __str__(self) -> str:
        """`HH:MM`, zero padded."""
        return f"{self.hour:02d}:{self.minute:02d}"


@dataclass(frozen=True)
class ScheduleSpec:
    """One project's daily run: its label, time, the command and the file its output goes to."""

    label: str
    at: DailyTime
    argv: tuple[str, ...]
    log: Path


@dataclass(frozen=True)
class ScheduleStatus:
    """Whether the daily run is registered and, when the scheduler says so, at what time."""

    installed: bool
    at: DailyTime | None = None

    def sentence(self) -> str:
        """The status in plain words."""
        if not self.installed:
            return "no daily nightly run is scheduled"
        when = f"at {self.at}" if self.at else "(the scheduler did not report its time)"
        return f"a daily nightly run is scheduled {when}"


@dataclass(frozen=True)
class Completed:
    """A finished scheduler call."""

    code: int
    output: str


class SchedulerSystem(Protocol):
    """The scheduler tools and files a platform's scheduler touches."""

    def run(self, tool: Tool, args: Sequence[str], stdin: str | None = None) -> Completed:
        """Run a scheduler tool and return its exit code and combined output."""
        ...

    def write(self, path: Path, data: bytes) -> None:
        """Write a file, creating its folder."""
        ...

    def delete(self, path: Path) -> None:
        """Delete a file if it exists."""
        ...

    def read(self, path: Path) -> bytes | None:
        """A file's bytes, or None when it does not exist."""
        ...


def label_for(project: str) -> str:
    """The scheduler's name for a project's nightly run."""
    return LABEL_PREFIX + _UNSAFE.sub("-", project)


# ---- macOS: a user LaunchAgent -------------------------------------------------------------


def launchd_plist(spec: ScheduleSpec) -> bytes:
    """The LaunchAgent property list: run the command daily at the spec's time."""
    document = {
        "Label": spec.label,
        "ProgramArguments": list(spec.argv),
        "StartCalendarInterval": {"Hour": spec.at.hour, "Minute": spec.at.minute},
        "StandardOutPath": str(spec.log),
        "StandardErrorPath": str(spec.log),
        "ProcessType": "Background",
    }
    return plistlib.dumps(document)


def launchd_time(plist: bytes) -> DailyTime | None:
    """The daily time in a LaunchAgent plist, or None when it has none."""
    when = plistlib.loads(plist).get("StartCalendarInterval")
    if not isinstance(when, dict) or "Hour" not in when or "Minute" not in when:
        return None
    return DailyTime(int(when["Hour"]), int(when["Minute"]))


@dataclass(frozen=True)
class MacScheduler:
    """launchd, in the user's own GUI domain (`launchctl bootstrap gui/<uid>`)."""

    system: SchedulerSystem
    home: Path
    uid: int

    def _plist(self, label: str) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{label}.plist"

    def _target(self, label: str) -> str:
        return f"gui/{self.uid}/{label}"

    def install(self, spec: ScheduleSpec) -> None:
        """Write the plist and load it, replacing a loaded one of the same label."""
        if self.system.run(Tool.LAUNCHCTL, ["print", self._target(spec.label)]).code == 0:
            _must(self.system.run(Tool.LAUNCHCTL, ["bootout", self._target(spec.label)]), "bootout")
        path = self._plist(spec.label)
        self.system.write(path, launchd_plist(spec))
        _must(
            self.system.run(Tool.LAUNCHCTL, ["bootstrap", f"gui/{self.uid}", str(path)]),
            "bootstrap",
        )

    def remove(self, label: str) -> None:
        """Unload the agent if loaded and delete its plist."""
        if self.system.run(Tool.LAUNCHCTL, ["print", self._target(label)]).code == 0:
            _must(self.system.run(Tool.LAUNCHCTL, ["bootout", self._target(label)]), "bootout")
        self.system.delete(self._plist(label))

    def status(self, label: str) -> ScheduleStatus:
        """Loaded in launchd and the time its plist names."""
        plist = self.system.read(self._plist(label))
        loaded = self.system.run(Tool.LAUNCHCTL, ["print", self._target(label)]).code == 0
        if plist is None or not loaded:
            return ScheduleStatus(installed=False)
        return ScheduleStatus(installed=True, at=launchd_time(plist))


# ---- Linux: a tagged line in the user's crontab --------------------------------------------


def _crontab_without(existing: str, label: str) -> list[str]:
    """The crontab's lines minus any line tagged with this label."""
    return [line for line in existing.splitlines() if not line.endswith(TAG + label)]


def _shell_quote(argv: Sequence[str]) -> str:
    """The argv as one POSIX shell command line."""
    return " ".join(_quoted(word) for word in argv)


def _quoted(word: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", word):
        return word
    return "'" + word.replace("'", "'\"'\"'") + "'"


def crontab_line(spec: ScheduleSpec) -> str:
    """The one crontab line: daily at the spec's time, output appended to the log, tagged."""
    command = f"{_shell_quote(spec.argv)} >> {_shell_quote([str(spec.log)])} 2>&1"
    return f"{spec.at.minute} {spec.at.hour} * * * {command}  {TAG}{spec.label}"


def crontab_with(existing: str, spec: ScheduleSpec) -> str:
    """The crontab text with this label's line added (or replaced); other lines are kept."""
    return "\n".join([*_crontab_without(existing, spec.label), crontab_line(spec)]) + "\n"


def crontab_time(existing: str, label: str) -> DailyTime | None:
    """The time of this label's crontab line, or None when it has no line."""
    for line in existing.splitlines():
        if line.endswith(TAG + label):
            minute, hour = line.split()[:2]
            return DailyTime(int(hour), int(minute))
    return None


@dataclass(frozen=True)
class LinuxScheduler:
    """The user's crontab; lines of other jobs are never touched."""

    system: SchedulerSystem

    def _current(self) -> str:
        """The crontab text; an account with no crontab yet reads as empty."""
        done = self.system.run(Tool.CRONTAB, ["-l"])
        if done.code != 0 and "no crontab" not in done.output.lower():
            raise ScheduleError(f"crontab -l failed: {done.output.strip()}")
        return "" if done.code != 0 else done.output

    def install(self, spec: ScheduleSpec) -> None:
        """Add this project's line to the crontab."""
        _must(self.system.run(Tool.CRONTAB, ["-"], crontab_with(self._current(), spec)), "crontab")

    def remove(self, label: str) -> None:
        """Take this project's line out of the crontab."""
        kept = "\n".join(_crontab_without(self._current(), label))
        _must(self.system.run(Tool.CRONTAB, ["-"], kept + "\n" if kept else ""), "crontab")

    def status(self, label: str) -> ScheduleStatus:
        """Whether the crontab has this project's line and its time."""
        at = crontab_time(self._current(), label)
        return ScheduleStatus(installed=at is not None, at=at)


# ---- Windows: Task Scheduler ---------------------------------------------------------------


def schtasks_create(spec: ScheduleSpec) -> list[str]:
    """Arguments of `schtasks` for a daily run at the spec's time, replacing a task of that name."""
    command = subprocess.list2cmdline(list(spec.argv))
    return [
        "/Create", "/F", "/SC", "DAILY", "/TN", spec.label, "/ST", str(spec.at),
        "/TR", command,
    ]  # fmt: skip


_START_TIME = re.compile(r"Start Time:\s*(\d{1,2}):(\d{2})")


def schtasks_time(query: str) -> DailyTime | None:
    """The start time in `schtasks /Query /V /FO LIST` output, or None when it does not say."""
    found = _START_TIME.search(query)
    return DailyTime(int(found.group(1)), int(found.group(2))) if found else None


@dataclass(frozen=True)
class WindowsScheduler:
    """Task Scheduler, through `schtasks`, in the user's own account."""

    system: SchedulerSystem

    def install(self, spec: ScheduleSpec) -> None:
        """Create or replace the task."""
        _must(self.system.run(Tool.SCHTASKS, schtasks_create(spec)), "schtasks /Create")

    def remove(self, label: str) -> None:
        """Delete the task if it exists."""
        if self.status(label).installed:
            _must(
                self.system.run(Tool.SCHTASKS, ["/Delete", "/F", "/TN", label]), "schtasks /Delete"
            )

    def status(self, label: str) -> ScheduleStatus:
        """Whether the task exists and the start time it reports."""
        done = self.system.run(Tool.SCHTASKS, ["/Query", "/V", "/FO", "LIST", "/TN", label])
        if done.code != 0:
            return ScheduleStatus(installed=False)
        return ScheduleStatus(installed=True, at=schtasks_time(done.output))


class Scheduler(Protocol):
    """What the three platforms share: install, remove and report one project's daily run."""

    def install(self, spec: ScheduleSpec) -> None:
        """Register the daily run."""
        ...

    def remove(self, label: str) -> None:
        """Unregister it."""
        ...

    def status(self, label: str) -> ScheduleStatus:
        """Report it."""
        ...


def scheduler_for(platform: Platform, system: SchedulerSystem, home: Path, uid: int) -> Scheduler:
    """The scheduler of `platform`; `home` and `uid` matter on macOS only."""
    if platform is Platform.MACOS:
        return MacScheduler(system, home, uid)
    if platform is Platform.LINUX:
        return LinuxScheduler(system)
    return WindowsScheduler(system)


def _must(done: Completed, what: str) -> None:
    """Raise ScheduleError with the tool's output when it did not exit 0."""
    if done.code != 0:
        raise ScheduleError(f"{what} failed (exit {done.code}): {done.output.strip()}")
