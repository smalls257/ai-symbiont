"""The settings the warning-budget run takes from the G6 results file."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "offline"


@pytest.fixture(scope="module")
def script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_warning_budget", SCRIPTS / "run_warning_budget.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def g6_file(tmp_path, **overrides):
    thresholds = {"0": {"chosen": 0.5}, "1": {"chosen": 0.6}, "2": {"chosen": 0.5}}
    document = {
        "smoke": False,
        "freeze_commit": "abc123",
        "calibration_train_only": {
            "counters_min_count": {"chosen": 4},
            "mushroom_threshold": thresholds,
        },
        **overrides,
    }
    path = tmp_path / "g6.json"
    path.write_text(json.dumps(document))
    return path


def test_settings_are_the_chosen_g6_values(script, tmp_path):
    settings = script.g6_settings(g6_file(tmp_path))
    assert settings.counters_min_count == 4
    assert settings.fly_thresholds == {0: 0.5, 1: 0.6, 2: 0.5}
    assert settings.freeze_commit == "abc123"


def test_a_smoke_g6_file_is_refused(script, tmp_path):
    with pytest.raises(ValueError, match="smoke"):
        script.g6_settings(g6_file(tmp_path, smoke=True))
