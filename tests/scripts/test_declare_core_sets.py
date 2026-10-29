"""The Core test-set declaration on hand-written records."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    spec = importlib.util.spec_from_file_location(
        "declare_core_sets", ROUTEB / "declare_core_sets.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_core_sets"] = module
    spec.loader.exec_module(module)
    return module


def _log(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_plain_records_keep_plain_graded_runs_by_cap(monkeypatch, tmp_path):
    core = load(monkeypatch)
    log = _log(
        tmp_path / "a.jsonl",
        [
            {"instance_id": "t", "step_limit": 75, "resolved": True},
            {"instance_id": "t", "step_limit": 50, "resolved": False, "arm": "plain"},
            {"instance_id": "t", "step_limit": 50, "resolved": True, "arm": "lesson"},
            {"instance_id": "t", "step_limit": 50, "resolved": None},
        ],
    )
    assert core.plain_records([log])["t"] == {50: [0, 1], 75: [1, 1]}


def test_estimate_prefers_the_cap_then_cap_50_then_unmeasured(monkeypatch):
    core = load(monkeypatch)
    assert core.estimate({50: [1, 4], 75: [1, 2]}) == (0.5, "plain runs at cap 75: 1 of 2")
    assert core.estimate({50: [1, 4], 75: [0, 0]})[1].startswith("plain runs at cap 50")
    assert core.estimate(None) == (None, "unmeasured")


def test_collection_never_takes_a_test_task_or_a_known_hard_one(monkeypatch):
    core = load(monkeypatch)
    pool = [
        {"instance_id": i, "subsystem": "dialects", "gold_changed_lines": "1"}
        for i in ("t", "hard", "new", "solved")
    ]
    rows = {i: {"created_at": "2024"} for i in ("t", "hard", "new", "solved")}
    records = {
        "hard": {50: [0, 1], 75: [0, 2]},
        "solved": {50: [1, 1], 75: [0, 0]},
        "t": {50: [1, 1], 75: [0, 0]},
    }
    assert core.collect_sqlglot(pool, {"t"}, records, rows) == ["solved", "new"]
