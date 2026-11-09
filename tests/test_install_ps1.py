"""install.ps1 runs as a scriptblock in the user's own PowerShell session and must not close it.

Failure guarded against: `exit` inside `& ([scriptblock]::Create(...))` ends the user's window, and
a bare `symbiont` path that does not exist on Windows (the console script is symbiont.exe).
"""

import re
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(encoding="utf-8")
CODE = "\n".join(line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#"))


def test_a_failure_throws_instead_of_closing_the_users_session():
    assert not re.search(r"^\s*exit\b", CODE, re.MULTILINE)
    assert CODE.count("throw ") == 2


def test_the_installed_program_is_symbiont_exe_on_windows():
    assert '"symbiont.exe"' in CODE
    assert "Join-Path $binDir $symbiont" in CODE
