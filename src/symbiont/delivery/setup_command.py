"""`symbiont setup`: register the plugin in every coding harness found on this machine.

`install.sh` and `install.ps1` know only `uv` and the package; which harness commands exist lives
in the harness registry (`Harness.plugin_setup`), so a new harness needs no installer-script
change. A harness whose CLI is missing gets its commands printed to run by hand, and a command
that fails is named with its exit code and makes the whole run exit 1.
"""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from symbiont.readers.harnesses import HARNESSES, Harness, UnknownHarnessError, harness

AUTO = "auto"
ALL = "all"
NONE = "none"
EXIT_USAGE = 2

# `claude plugin marketplace add` is assumed to say "already" for a registered marketplace, so a
# re-run exits 0. [hypothesis: not run here, as that would change the owner's configuration.]
# An unrecognized wording still fails loudly.
ALREADY_DONE = "already"


@dataclass(frozen=True)
class CommandResult:
    """What a harness command did: its exit code and its output (stdout and stderr together)."""

    exit_code: int
    output: str


CommandRunner = Callable[[tuple[str, ...]], CommandResult]
PathLookup = Callable[[str], str | None]
_CAPTURE: dict[str, Any] = {
    "capture_output": True,
    "text": True,
    "stdin": subprocess.DEVNULL,
    "check": False,
}


def _run_claude(rest: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["claude", *rest], **_CAPTURE)


def _run_muse(rest: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["muse", *rest], **_CAPTURE)


# One literal program name per call site: the sym-subprocess-literal-command gate refuses a
# computed command. A registry CLI missing here fails the program-runner test.
CLI_PROGRAMS = {"claude": _run_claude, "muse": _run_muse}


def run_command(argv: tuple[str, ...]) -> CommandResult:
    """Run one harness CLI command, capturing its output; an unlisted program raises."""
    runner = CLI_PROGRAMS.get(argv[0])
    if runner is None:
        raise UnknownHarnessError(f"no runner for {argv[0]!r}; known: {', '.join(CLI_PROGRAMS)}")
    done = runner(argv[1:])
    return CommandResult(done.returncode, (done.stdout + done.stderr).strip())


def add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    """The `--harness` choice shared by `symbiont setup` and the install scripts."""
    parser.add_argument(
        "--harness",
        default=AUTO,
        metavar="auto|all|none|<id>",
        help="auto: every harness whose CLI is on PATH (default); all; none; or one harness id",
    )


def run_setup(
    args: argparse.Namespace,
    runner: CommandRunner = run_command,
    which: PathLookup = shutil.which,
) -> int:
    """Register the plugin per the choice; 0 unless a command failed, 2 for an unknown id."""
    try:
        chosen = _chosen(args.harness, which)
    except UnknownHarnessError as refused:
        _error(f"symbiont setup: {refused}")
        return EXIT_USAGE
    if not chosen:
        _say("symbiont setup: no harness chosen; nothing to register")
        return 0
    failures = [name for entry in chosen for name in _register(entry, runner, which)]
    for command in failures:
        _error(f"symbiont setup: failed: {command}")
    return 1 if failures else 0


def main_setup(
    argv: Sequence[str],
    runner: CommandRunner = run_command,
    which: PathLookup = shutil.which,
) -> int:
    """Parse `setup` arguments and run; the entry the tests and the script wrappers share."""
    parser = argparse.ArgumentParser(prog="symbiont setup")
    add_setup_arguments(parser)
    return run_setup(parser.parse_args(argv), runner, which)


def _chosen(choice: str, which: PathLookup) -> list[Harness]:
    if choice == NONE:
        return []
    if choice == ALL:
        return list(HARNESSES)
    if choice == AUTO:
        found = [entry for entry in HARNESSES if _cli(entry) and which(_cli(entry))]
        # With no harness CLI at all, still show every command: the developer installs one later.
        return found or list(HARNESSES)
    return [harness(choice)]


def _say(line: str) -> None:
    """Write a progress line; `print` is reserved for cli.py by the lint config."""
    sys.stdout.write(line + "\n")


def _error(line: str) -> None:
    sys.stderr.write(line + "\n")


def _cli(entry: Harness) -> str:
    return entry.plugin_setup[0][0]


def _register(entry: Harness, runner: CommandRunner, which: PathLookup) -> list[str]:
    """Run or print one harness's commands; returns the failed ones as the developer would type."""
    if not which(_cli(entry)):
        _say(f"{entry.label}: {_cli(entry)} is not on PATH. Run these by hand:")
        for argv in entry.plugin_setup:
            _say(f"  {' '.join(argv)}")
        return []
    failed: list[str] = []
    for argv in entry.plugin_setup:
        _say(f"{entry.label}: {' '.join(argv)}")
        result = runner(argv)
        if result.exit_code == 0 or _already_done(argv, result):
            continue
        _error(f"  exit {result.exit_code}: {result.output}")
        failed.append(f"{' '.join(argv)} (exit {result.exit_code})")
    return failed


def _already_done(argv: tuple[str, ...], result: CommandResult) -> bool:
    return "add" in argv and ALREADY_DONE in result.output.lower()
