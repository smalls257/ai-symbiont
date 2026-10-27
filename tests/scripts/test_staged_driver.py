"""The staged calibration driver with Glimmer and Docker stubbed: bands, blocked stop, gate."""

import importlib.util
import json
import sys
import types
from collections import namedtuple
from pathlib import Path

import pytest

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"
Setting = namedtuple("Setting", "reasoning step_limit wall_limit_s")


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so the stubs of one test never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name, run_once=None):
    stub = types.ModuleType("run_calibration")
    stub.IMAGE, stub.MODEL, stub.Setting = "image", "model", Setting
    stub.run_once = run_once
    monkeypatch.setitem(sys.modules, "run_calibration", stub)
    monkeypatch.syspath_prepend(str(CALIBRATION))
    monkeypatch.delitem(sys.modules, "staged_summary", raising=False)
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", CALIBRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def rec(run, resolved, reasoning="low"):
    return {"instance_id": "t", "run": run, "reasoning": reasoning, "resolved": resolved}


def test_band_waits_for_the_screen_run_and_all_three_runs(monkeypatch):
    summary = load(monkeypatch, "staged_summary")
    assert summary.band_of(None, []) == "pending"
    assert summary.band_of("low", []) == "pending"
    assert summary.band_of("low", [rec(1, True)]) == "pending"
    assert summary.band_of("low", [rec(1, True), rec(2, False), rec(3, False)]) == "in_band"


def test_band_is_history_when_the_screen_failed_or_all_three_solved(monkeypatch):
    summary = load(monkeypatch, "staged_summary")
    assert summary.band_of("low", [rec(1, False)]) == "history"
    assert summary.band_of("low", [rec(n, True) for n in (1, 2, 3)]) == "history"


def test_task_entry_counts_only_graded_runs_of_the_chosen_setting(monkeypatch):
    summary = load(monkeypatch, "staged_summary")
    runs = [rec(1, True), rec(2, None), rec(1, True, reasoning="medium")]
    entry = summary.task_entry("t", runs, "low")
    assert (entry["solved_with_setting"], entry["graded_with_setting"]) == (1, 1)
    assert len(entry["runs"]) == 3 and entry["band"] == "pending"


def test_run_totals_ignore_runs_without_a_wall_time(monkeypatch):
    summary = load(monkeypatch, "staged_summary")
    records = [rec(1, True) | {"wall_s": 3600}, rec(2, None)]
    totals = summary.run_totals(records)
    assert totals == {"n_runs": 2, "total_hours": 1.0, "mean_wall_s": 3600.0, "ungraded_runs": 1}


def make_workdir(tmp_path, n_tasks=12):
    (tmp_path / "data").mkdir()
    (tmp_path / "runs").mkdir()
    ids = [f"task{n:02d}" for n in range(n_tasks)]
    rows = [{"instance_id": iid} for iid in ids]
    pool = [{"instance_id": iid, "gold_changed_lines": n} for n, iid in enumerate(ids)]
    (tmp_path / "data/sqlglot_rows.json").write_text(json.dumps(rows))
    (tmp_path / "data/pool.json").write_text(json.dumps({"pool": pool}))
    return tmp_path


def fake_run(resolved):
    def run_once(row, run, setting, stage, traj_dir):
        return {
            "instance_id": row["instance_id"],
            "run": run,
            "reasoning": setting.reasoning,
            "step_limit": setting.step_limit,
            "stage": stage,
            "resolved": resolved(row["instance_id"], run, setting),
            "error": "docker down",
        }

    return run_once


def test_three_ungraded_runs_in_a_row_stop_the_driver_as_blocked(monkeypatch, tmp_path):
    staged = load(monkeypatch, "staged", fake_run(lambda *args: None))
    driver = staged.Driver(make_workdir(tmp_path))
    driver.run()
    summary = json.loads(driver.summary_path.read_text())
    assert summary["status"] == "blocked" and "docker down" in summary["blocked_reason"]
    assert summary["ungraded_runs"] == 3 and "finished" in summary


def test_screen_gate_fails_when_medium_was_tried_and_nothing_solves(monkeypatch, tmp_path):
    staged = load(monkeypatch, "staged", fake_run(lambda *args: False))
    driver = staged.Driver(make_workdir(tmp_path))
    driver.run()
    summary = json.loads(driver.summary_path.read_text())
    assert summary["status"] == "gate_fail"
    assert [d["what"] for d in summary["decisions"]] == ["checkpoint", "screen_done"]
    assert summary["setting"] == "low", "a tie keeps low"


def test_solved_tasks_get_two_more_runs_and_land_in_band_or_history(monkeypatch, tmp_path):
    def solves_first_task_once(iid, run, setting):
        return iid == "task00" and run in (1, 2)

    staged = load(monkeypatch, "staged", fake_run(solves_first_task_once))
    driver = staged.Driver(make_workdir(tmp_path))
    driver.run()
    summary = json.loads(driver.summary_path.read_text())
    assert summary["status"] == "done"
    assert summary["band_counts"] == {"in_band": 1, "history": 11, "pending": 0}


def test_a_restarted_driver_does_not_rerun_graded_records(monkeypatch, tmp_path):
    calls = []

    def run_once(row, run, setting, stage, traj_dir):
        calls.append((row["instance_id"], run))
        return fake_run(lambda *args: False)(row, run, setting, stage, traj_dir)

    staged = load(monkeypatch, "staged", run_once)
    workdir = make_workdir(tmp_path)
    staged.Driver(workdir).run()
    first = len(calls)
    staged.Driver(workdir).run()
    assert first > 0 and len(calls) == first


def test_blocked_error_names_the_stop_reason(monkeypatch):
    staged = load(monkeypatch, "staged")
    assert issubclass(staged.BlockedError, RuntimeError)
    with pytest.raises(staged.BlockedError, match="3 ungraded runs in a row"):
        raise staged.BlockedError("3 ungraded runs in a row")
