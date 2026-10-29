"""The Core MDE arithmetic on hand-made numbers."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "core_mde.py"


def load():
    spec = importlib.util.spec_from_file_location("core_mde", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mde_and_runs_needed_follow_the_paired_formula():
    module = load()
    assert module.z_sum() == pytest.approx(2.8016, abs=1e-3)
    assert module.mde(0.1, 45, 2) == pytest.approx(2.8016 * (0.2 / 90) ** 0.5, abs=1e-4)
    assert module.mde(0.1, 45, module.runs_needed(0.1, 45, 0.05)) <= 0.05


def test_variance_from_repeats_and_from_a_run_pair():
    module = load()
    assert module.repeat_variance({"a": [1, 2], "b": [0, 3], "c": [1, 1]}) == (0.25, 2)
    first, second = {"a": True, "b": False}, {"a": False, "b": False}
    assert module.pair_variance(first, second) == (0.25, 2)


def test_records_keep_plain_graded_runs_of_listed_tasks(tmp_path):
    module = load()
    rows = [
        {"instance_id": "a", "step_limit": 50, "resolved": True},
        {"instance_id": "a", "step_limit": 50, "resolved": False, "arm": "lesson"},
        {"instance_id": "z", "step_limit": 50, "resolved": True},
    ]
    log = tmp_path / "l.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert module.records_by_cap([log], {"a"}) == {50: {"a": [1, 1]}}
