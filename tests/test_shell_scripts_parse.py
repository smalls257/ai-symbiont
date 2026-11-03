"""Every tracked shell script parses under bash and has LF line ends, on every platform.

Failure guarded against: a CRLF checkout (Git for Windows default) that makes `sh` choke on `\\r`,
which would take down the plugin hook wrapper and the ops scripts without a visible error. This is
also the Windows counterpart of the ops/ tests that need docker, flock and POSIX signals.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery

ROOT = Path(__file__).resolve().parents[1]


def tracked_shell_scripts() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.sh"], capture_output=True, text=True, check=True
    )
    return [ROOT / line for line in listed.stdout.splitlines() if line]


def test_the_repository_has_shell_scripts_to_check():
    assert len(tracked_shell_scripts()) >= 5


@pytest.mark.parametrize(
    "script", tracked_shell_scripts(), ids=lambda p: p.relative_to(ROOT).as_posix()
)
def test_a_shell_script_has_unix_line_ends_and_parses(script):
    assert b"\r" not in script.read_bytes(), f"{script} has CR line ends; sh would fail on them"
    bash = shutil.which("bash")
    assert bash, "bash (Git Bash on Windows) is needed to parse the shell scripts"
    parsed = subprocess.run(
        [bash, "-n", script.as_posix()], capture_output=True, text=True, check=False
    )
    assert parsed.returncode == 0, parsed.stderr
