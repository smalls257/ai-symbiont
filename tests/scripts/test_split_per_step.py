"""split_per_step keeps every summary value byte-identical and the per-step file checkable."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "offline" / "split_per_step.py"
# Summary fields of results/offline-selection.json from before the per-step arrays moved out
# (generated once from the then-current file, per_step dropped); history-independent.
PRE_SPLIT_SUMMARY = ROOT / "tests" / "fixtures" / "offline" / "pre-split-summary.json"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("split_per_step", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document():
    return {
        "smoke": False,
        "rows": {"a": {"x": 0.1}},
        "per_step": {"a": [{"t": "01"}], "b": [{"t": "10"}, {"t": "11"}]},
    }


def test_split_keeps_summary_and_points_at_the_checked_file(mod, tmp_path):
    doc = document()
    written = tmp_path / "per-step.json"
    written.write_text(json.dumps(doc["per_step"]))
    summary = mod.split(doc, "per-step.json", written, {"host": "h"})
    assert "per_step" not in summary
    assert mod.changed_values(doc, summary) == []
    assert summary["per_step_file"]["rows_per_arm"] == {"a": 1, "b": 2}
    assert summary["per_step_file"]["sha256"] == mod.sha256_of(written)


def test_changed_summary_value_is_reported(mod, tmp_path):
    doc = document()
    written = tmp_path / "p.json"
    written.write_text("{}")
    summary = mod.split(doc, "p.json", written, {})
    edited = {**summary, "rows": {"a": {"x": 0.2}}}
    assert mod.changed_values(doc, edited) == ["rows"]


def test_load_refuses_a_per_step_file_that_does_not_match_its_hash(mod, tmp_path):
    doc = document()
    written = tmp_path / "p.json"
    written.write_text(json.dumps(doc["per_step"]))
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(mod.split(doc, "p.json", written, {})))
    assert mod.load_per_step(summary_path, tmp_path) == doc["per_step"]
    written.write_text("{}")
    with pytest.raises(ValueError, match="sha256"):
        mod.load_per_step(summary_path, tmp_path)


def test_committed_results_summary_equals_the_pre_split_summary(mod):
    old = json.loads(PRE_SPLIT_SUMMARY.read_text())
    new = json.loads((ROOT / "results" / "offline-selection.json").read_text())
    assert mod.changed_values(old, new) == []


def test_a_changed_summary_number_fails_the_pre_split_comparison(mod):
    old = json.loads(PRE_SPLIT_SUMMARY.read_text())
    new = json.loads((ROOT / "results" / "offline-selection.json").read_text())
    key = next(k for k, v in old.items() if isinstance(v, dict) and k in new)
    new[key] = {**new[key], "tampered": 1}
    assert mod.changed_values(old, new) == [key]
