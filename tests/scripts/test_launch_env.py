"""launch.py must stop on a missing Glimmer endpoint before loading rows or writing a summary."""

import os
import subprocess
import sys
from pathlib import Path

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"

# The dev environment has no litellm or mini-SWE-agent; the entry point must fail before using them.
RUNNER = f"""
import runpy, sys
from unittest.mock import MagicMock
for name in ("yaml", "litellm", "litellm.exceptions", "minisweagent", "minisweagent.agents",
             "minisweagent.agents.default", "minisweagent.config", "minisweagent.environments",
             "minisweagent.environments.docker", "minisweagent.models",
             "minisweagent.models.litellm_model"):
    sys.modules[name] = MagicMock()
sys.path.insert(0, {str(CALIBRATION)!r})
sys.argv = ["launch.py", sys.argv[1]]
runpy.run_path({str(CALIBRATION / "launch.py")!r}, run_name="__main__")
"""


def test_missing_endpoint_exits_before_any_work(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SYMBIONT_", "GIT_"))}
    result = subprocess.run(
        [sys.executable, "-c", RUNNER, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "SYMBIONT_GLIMMER_URL" in result.stderr
    assert list(tmp_path.iterdir()) == []
