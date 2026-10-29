"""The Core collection launcher waits for the Strix marker and refuses without its inputs."""

import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibration" / "core_collect.sh"
ENV = {"PATH": "/usr/bin:/bin", "SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1/v1"}


def _work(tmp_path):
    for path in (
        "calibration-general/launch.py",
        "runs-bench/repo/scripts/swev/launch_swev.sh",
        ".venv/bin/activate",
        "runs-core-collect/collect-sqlglot.jsonl",
        "runs-core-collect/core-test-set.json",
        "runs-core-collect/core_collect_manifest.py",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    return tmp_path / "runs-core-collect"


def _run(tmp_path, env):
    return subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_refuses_without_its_inputs(tmp_path):
    found = _run(tmp_path, ENV)
    assert found.returncode == 66
    assert "missing" in found.stderr


def test_waits_for_the_strix_marker_until_the_deadline(tmp_path):
    out = _work(tmp_path)
    env = ENV | {"POLL_S": "1", "DEADLINE": str(int(time.time()) + 2)}
    found = _run(tmp_path, env)
    assert found.returncode == 75
    log = (out / "collect.log").read_text()
    assert "waiting: no strix-ok marker" in log
    assert "start sqlglot collection" not in log
