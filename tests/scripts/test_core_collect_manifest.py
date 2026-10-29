"""The Core collection manifest on hand-written run logs."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "routeb" / "core_collect_manifest.py"


def load():
    spec = importlib.util.spec_from_file_location("core_collect_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cal2(run_dir, rows):
    run_dir.mkdir(parents=True)
    (run_dir / "calibration.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for row in rows:
        path = run_dir / "traj" / row["instance_id"]
        path.mkdir(parents=True, exist_ok=True)
        config = {"info": {"config": {"model": {"model_name": "muse-spark-1.3-contributor"}}}}
        (path / f"cal2-run{row['run']}-low.traj.json").write_text(json.dumps(config))


def test_keeps_resolved_runs_and_leaves_out_test_tasks(tmp_path):
    module = load()
    base = {"stage": "cal2", "reasoning": "low", "step_limit": 75, "steps": 30}
    _cal2(
        tmp_path / "work" / "runs-a",
        [
            base | {"instance_id": "early", "run": 1, "resolved": True},
            base | {"instance_id": "early", "run": 2, "resolved": False},
            base | {"instance_id": "held", "run": 1, "resolved": True},
        ],
    )
    found, skipped = module.manifest({"test": [{"task": "held"}]}, [tmp_path / "work" / "runs-a"])
    assert [(e["task"], e["run"], e["run_dir"], e["source"]) for e in found] == [
        ("early", 1, str(tmp_path / "work" / "runs-a"), "teacher/spark")
    ]
    assert skipped == 1
    assert found[0]["model"] == "muse-spark-1.3-contributor"  # the trajectory's, not the record's


def test_a_resolved_run_without_its_trajectory_raises(tmp_path):
    module = load()
    run_dir = tmp_path / "runs-b"
    run_dir.mkdir()
    swev = {
        "instance_id": "d",
        "phase": "history",
        "arm": "plain",
        "run": 1,
        "step_limit": 75,
        "resolved": True,
    }
    (run_dir / "swev.jsonl").write_text(json.dumps(swev) + "\n")
    with pytest.raises(FileNotFoundError, match="without a trajectory"):
        module.passing_runs(run_dir)
