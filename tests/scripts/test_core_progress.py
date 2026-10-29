"""The Core collection progress count and its midpoint check."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "core_progress.py"


def load():
    spec = importlib.util.spec_from_file_location("core_progress", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_tally_counts_new_and_reused_passes_and_skips_errors(tmp_path):
    module = load()
    _write(
        tmp_path / "sqlglot/calibration.jsonl",
        [
            {"instance_id": "a", "resolved": True},
            {"instance_id": "a", "resolved": False},
            {"instance_id": "b", "resolved": False, "error_kind": "model_api"},
        ],
    )
    _write(tmp_path / "django/swev.jsonl", [{"instance_id": "d", "resolved": True}])
    _write(
        tmp_path / "reusable-passing.jsonl",
        [
            {"task": "a", "arm": "plain"},
            {"task": "c", "arm": "plain"},
            {"task": "x", "arm": "lesson"},
        ],
    )
    assert module.tally(tmp_path) == {"graded": 3, "new_passes": 2, "passes": 4, "tasks": 3}


def test_verdict_trips_only_at_the_midpoint():
    module = load()
    assert module.verdict({"graded": 10, "passes": 1, "tasks": 1}, 128) == "before midpoint"
    assert module.verdict({"graded": 64, "passes": 29, "tasks": 20}, 128).startswith("MIDPOINT LOW")
    assert module.verdict({"graded": 64, "passes": 30, "tasks": 15}, 128) == "midpoint ok"
