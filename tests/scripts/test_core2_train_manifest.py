"""Core D2 manifest: refusals, earliest-by-date cap, one movable directory."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    spec = importlib.util.spec_from_file_location(
        "core2_train_manifest", ROUTEB / "core2_train_manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("core_collect_manifest", None)


def test_the_cap_keeps_the_earliest_passes_by_date(mod):
    passes = [{"task": f"a__a-{n}", "path": Path("x")} for n in (3, 1, 2)]
    dates = {"a__a-1": "2020", "a__a-2": "2021", "a__a-3": "2019"}
    assert [r["task"] for r in mod.capped(passes, dates, 2)] == ["a__a-1", "a__a-3"]
    assert len(mod.capped(passes, {}, 3)) == 3  # at or under the cap needs no dates
    with pytest.raises(KeyError):
        mod.capped(passes, {}, 2)


def test_test_tasks_and_later_candidates_are_refused(mod):
    passes = [{"task": "a__a-1", "path": None}, {"task": "a__a-9", "path": None}]
    kept, refused = mod.refuse(passes, {"a__a-9"})
    assert [r["task"] for r in kept] == ["a__a-1"] and refused == 1


def test_a_resolved_run_without_its_trajectory_raises(mod, tmp_path):
    (tmp_path / "runs.jsonl").write_text(
        json.dumps({"instance_id": "a__a-1", "resolved": True}) + "\n"
    )
    with pytest.raises(FileNotFoundError):
        mod.new_repo_passes(tmp_path)


def test_write_copies_trajectories_and_records_the_manifest_hash(mod, tmp_path):
    src = tmp_path / "t.json"
    src.write_text("{}")
    out = tmp_path / "out"
    counts = mod.write(
        out, [{"task": "a__a-1", "path": src}], refused={"test_or_later_candidate": 2}, cap=14
    )
    assert (out / "traj" / "a__a-1.traj.json").is_file()
    row = json.loads((out / "manifest.jsonl").read_text())
    assert row == {"instance_id": "a__a-1", "path": "traj/a__a-1.traj.json", "resolved": True,
                   "source": "teacher/spark"}  # fmt: skip
    assert counts["per_repo"] == {"a__a": 1} and counts["refused"] == {"test_or_later_candidate": 2}
    assert len(counts["manifest_sha256"]) == 64


def test_a_pooled_repository_keeps_only_passes_inside_its_earlier_pool(mod):
    passes = [{"task": "s__s-1", "path": None}, {"task": "s__s-2", "path": None},
              {"task": "d__d-7", "path": None}]  # fmt: skip
    kept, outside = mod.outside_earlier_pool(passes, {"s__s-1"})
    assert [r["task"] for r in kept] == ["s__s-1", "d__d-7"] and outside == 1
