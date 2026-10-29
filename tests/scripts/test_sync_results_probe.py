"""The sync script's liveness probe must tell a dead driver from a live one (Silent Fallback guard).

`ssh` and `sleep` are shimmed on PATH: ssh runs the piped command locally in a fake desktop work
dir, sleep returns at once so the retry pauses do not slow the test.
"""

import contextlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

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
    # The script asks "is launch.py or staged.py running?" machine-wide; on a laptop with real
    # drivers that is always yes and the probe loops forever. The shim looks only for this test's
    # own tag, so the answer depends on the test, not on the host.
    tag = f"fake-driver-{tmp_path.name}"
    (shims / "pgrep").write_text(f'#!/bin/bash\nexec /usr/bin/pgrep -f "{tag}"\n')
    env_tag = tag
    for shim in shims.iterdir():
        shim.chmod(0o755)
    repo = tmp_path / "repo"
    (repo / "results").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SYMBIONT_", "GIT_"))}
    env |= {
        "PATH": f"{shims}:{env['PATH']}",
        "SYMBIONT_DESKTOP_SSH": "user@desktop.example.invalid",
        "SYMBIONT_DESKTOP_WORKDIR": str(desktop),
        "FAKE_DRIVER_TAG": env_tag,
    }
    return env, repo


def _start(env: dict[str, str], repo: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["bash", str(SCRIPT), str(repo)],
        env=env,
        stdout=(repo.parent / "out.log").open("w"),
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,  # its own process group, so teardown can kill every child
    )


def _stop(proc: subprocess.Popen) -> None:
    """Kill the script's whole process group and wait; raises if anything in it survives."""
    with contextlib.suppress(ProcessLookupError):  # the group may already be gone
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise AssertionError(f"processes of group {proc.pid} survived the teardown")


def test_probe_reports_dead_driver(tmp_path):
    env, repo = _fixture(tmp_path)
    proc = _start(env, repo)
    try:
        proc.wait(timeout=30)
        assert proc.returncode == 3
        assert "STOP: driver not running" in (tmp_path / "out.log").read_text()
    finally:
        _stop(proc)


def test_probe_sees_live_driver(tmp_path):
    env, repo = _fixture(tmp_path)
    driver = subprocess.Popen(
        ["bash", "-c", "/bin/sleep 300; true", env["FAKE_DRIVER_TAG"]], start_new_session=True
    )
    proc = _start(env, repo)
    try:
        time.sleep(2)
        assert proc.poll() is None, "script stopped although a driver process exists"
    finally:
        _stop(proc)
        _stop(driver)


def test_no_child_of_a_looping_probe_survives_the_teardown(tmp_path):
    env, repo = _fixture(tmp_path)
    driver = subprocess.Popen(
        ["bash", "-c", "/bin/sleep 300; true", env["FAKE_DRIVER_TAG"]], start_new_session=True
    )
    proc = _start(env, repo)
    try:
        time.sleep(2)
        assert proc.poll() is None
    finally:
        _stop(proc)  # raises AssertionError itself if any process of the group is left
        _stop(driver)
    with pytest.raises(ProcessLookupError):
        os.killpg(proc.pid, 0)
