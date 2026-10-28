"""Opens the calibration Docker environment wrapped for an Act 2 arm (periphery glue)."""

import sys
from pathlib import Path

from symbiont.delivery.mini_swe_wrapper import NotedEnvironment, WrapMode, WrapSettings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calibration"))
from run_calibration import _open_environment  # noqa: E402  needs the sys.path entry above


def open_noted_environment(
    mode: WrapMode, port: int, session_id: str, project: str
) -> NotedEnvironment:
    """A fresh calibration container; PLAIN leaves it untouched, NOTES adds the service's notes."""
    return NotedEnvironment(_open_environment(), WrapSettings(mode, port, session_id, project))
