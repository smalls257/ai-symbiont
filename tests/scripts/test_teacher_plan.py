"""Teacher-run task choice: skip reliable plain passes, never a test-set task."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "teacher_plan.py"


def load():
    spec = importlib.util.spec_from_file_location("teacher_plan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reliable_needs_two_graded_plain_runs_all_solved(tmp_path):
    module = load()
    rows = [
        {"instance_id": "a", "resolved": True},
        {"instance_id": "a", "resolved": True},
        {"instance_id": "b", "resolved": True},
        {"instance_id": "b", "resolved": True, "error_kind": "model_api"},
        {"instance_id": "c", "resolved": True, "arm": "teacher"},
    ]
    log = tmp_path / "l.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    records = module.plain_record([log])
    assert module.reliable(records["a"]) and not module.reliable(records["b"])
    assert "c" not in records


def test_plan_skips_reliable_tasks_and_refuses_test_tasks():
    module = load()
    test_set = {"test": [{"task": "t"}], "collect": {"sqlglot": ["a", "b"], "django": ["d"]}}
    assert module.plan(test_set, {"a": [2, 2]}) == {"sqlglot": ["b"], "django": ["d"]}
    test_set["collect"]["django"].append("t")
    with pytest.raises(ValueError, match="test-set tasks"):
        module.plan(test_set, {})
