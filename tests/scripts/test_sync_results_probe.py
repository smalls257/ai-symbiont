"""The sync script's liveness probe must tell a dead driver from a live one (Silent Fallback guard).

`ssh` and `sleep` are shimmed on PATH: ssh runs the piped command locally in a fake desktop work
dir, sleep returns at once so the retry pauses do not slow the test.
"""

import json
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibration" / "sync_results.sh"


def _fixture(tmp_path: Path) -> tuple[dict[str, str], Path]:
    shims = tmp_path / "shims"
    shims.mkdir()
    desktop = tmp_path / "desktop"
    (desktop / "runs").mkdir(parents=True)
    summary = {"status": "running", "n_runs": 1, "band_counts": {}}
    (desktop / "runs" / "calibration-glimmer.json").write_text(json.dumps(summary))
    (shims / "ssh").write_text(f'#!/bin/bash\ncd "{desktop}" && exec bash -s\n')
    (shims / "sleep").write_text("#!/bin/bash\nexit 0\n")
    for shim in shims.iterdir():
        shim.chmod(0o755)
    repo = tmp_path / "repo"
    (repo / "results").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SYMBIONT_", "GIT_"))}
    env |= {
        "PATH": f"{shims}:{env['PATH']}",
        "SYMBIONT_DESKTOP_SSH": "user@desktop.example.invalid",
        "SYMBIONT_DESKTOP_WORKDIR": str(desktop),
    }
    return env, repo


def _start(env: dict[str, str], repo: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["bash", str(SCRIPT), str(repo)],
        env=env,
        stdout=(repo.parent / "out.log").open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_probe_reports_dead_driver(tmp_path):
    env, repo = _fixture(tmp_path)
    proc = _start(env, repo)
    proc.wait(timeout=30)
    assert proc.returncode == 3
    assert "STOP: driver not running" in (tmp_path / "out.log").read_text()


def test_probe_sees_live_driver(tmp_path):
    env, repo = _fixture(tmp_path)
    driver = subprocess.Popen(["bash", "-c", "/bin/sleep 300; true", "launch.py"])
    proc = _start(env, repo)
    try:
        time.sleep(2)
        assert proc.poll() is None, "script stopped although a launch.py process exists"
    finally:
        proc.kill()
        driver.kill()
        proc.wait()
        driver.wait()
