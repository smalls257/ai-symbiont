"""sync_results.sh must refuse to run without the desktop variables (Silent Fallback guard)."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibration" / "sync_results.sh"


def _run(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYMBIONT_")} | extra_env
    return subprocess.run(
        ["bash", str(SCRIPT), "/nonexistent"], env=env, capture_output=True, text=True, timeout=20
    )


def test_missing_ssh_target_fails_loudly():
    r = _run({})
    assert r.returncode != 0
    assert "SYMBIONT_DESKTOP_SSH" in r.stderr


def test_missing_workdir_fails_loudly():
    r = _run({"SYMBIONT_DESKTOP_SSH": "user@desktop.example.invalid"})
    assert r.returncode != 0
    assert "SYMBIONT_DESKTOP_WORKDIR" in r.stderr
