"""Control-adapter teacher tasks: other repos only, one per repo, stop rules."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


def load(monkeypatch, name):
    monkeypatch.setitem(sys.modules, "duckdb", types.ModuleType("duckdb"))
    spec = importlib.util.spec_from_file_location(name, ROUTEB / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_small_task_per_allowed_repo(monkeypatch):
    module = load(monkeypatch, "control_candidates")
    patch = lambda n: "".join(f"+x{i}\n" for i in range(n))  # noqa: E731
    rows = [
        {"instance_id": "a-2", "repo": "a", "patch": patch(5), "docker_image": "i"},
        {"instance_id": "a-1", "repo": "a", "patch": patch(2), "docker_image": "i"},
        {"instance_id": "b-1", "repo": "b", "patch": patch(40), "docker_image": "i"},
        {"instance_id": "c-1", "repo": "c", "patch": patch(1), "docker_image": None},
        {"instance_id": "s-1", "repo": "tobymao/sqlglot", "patch": patch(1), "docker_image": "i"},
    ]
    picked = module.one_per_repo(rows, {"tobymao/sqlglot"}, 10)
    assert [row["instance_id"] for row in picked] == ["a-1"]
    assert module.changed_lines("--- a/x\n+++ b/x\n+y\n-z\n") == 2


def test_control_refuses_held_tasks_and_stops_at_cap_or_target(monkeypatch, tmp_path):
    module = load(monkeypatch, "control_teacher")
    test_set = tmp_path / "t.json"
    test_set.write_text(json.dumps({"test": [{"task": "held"}]}))
    with pytest.raises(ValueError, match="held-out"):
        module.refuse_held([{"instance_id": "held", "repo": "x/y"}], test_set)
    with pytest.raises(ValueError, match="Core"):
        module.refuse_held([{"instance_id": "d", "repo": "django/django"}], test_set)
    (tmp_path / "traj").mkdir()
    (tmp_path / "traj" / "p.traj.json").write_text("x" * 35)
    records = [{"instance_id": "p", "resolved": True}, {"instance_id": "f", "resolved": False}]
    assert module.passing_tokens(records, tmp_path) == 10
    args = types.SimpleNamespace(cap_usd=3.0, target_tokens=10, out=tmp_path)
    monkeypatch.setattr(module, "phase_spent", lambda: 0.0)
    assert module.stop_reason(records, args) is None  # too few passes yet
    monkeypatch.setattr(module, "MIN_PASSES", 1)
    assert module.stop_reason(records, args) == "token target reached"
    monkeypatch.setattr(module, "phase_spent", lambda: 2.9)
    assert module.stop_reason([], args) == "phase cap reached"


def test_core_teacher_runs_refuse_later_candidates_not_core_repositories(monkeypatch, tmp_path):
    module = load(monkeypatch, "control_teacher")
    test_set = tmp_path / "t.json"
    test_set.write_text(json.dumps({"test": []}))
    split = tmp_path / "split.json"
    split.write_text(json.dumps({"a__a": {"keep_ids": ["a-9"]}, "b__b": {"keep_ids": []}}))
    later = module.later_candidate_ids(split)
    assert later == {"a-9"}
    module.refuse_held([{"instance_id": "a-1", "repo": "django/django"}], test_set, later)
    with pytest.raises(ValueError, match="later-candidate"):
        module.refuse_held([{"instance_id": "a-9", "repo": "a/a"}], test_set, later)
