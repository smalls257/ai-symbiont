"""Core D2 report and early stop on fake run directories."""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
PT = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def mods(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    import core2_report
    import core2_test_plan
    import core2_test_run

    yield core2_report, core2_test_plan, core2_test_run
    for name in ("core2_report", "core2_test_plan", "core2_test_run", "core2_test_claims"):
        sys.modules.pop(name, None)


def phase(run, plan, out, executor, now=None):
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    clock = now or (lambda: datetime(2026, 10, 31, 9, 0, tzinfo=PT))
    return run.Phase(executor, out, arms, clock, "strix")


def test_report_counts_voids_drops_and_incomplete_tasks_per_arm_and_server(mods, tmp_path):
    report, plan, run = mods
    ids = ["a", "b"]

    def executor(spec):
        if spec.task == "b":
            return {"resolved": None, "error_kind": "infra"}
        return {"resolved": spec.arm is plan.Arm.A}

    run.run_phase(ids, phase(run, plan, tmp_path, executor))
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    out = report.report(tmp_path, ids, arms)
    assert out["dropped_tasks"] == 1 and out["complete_tasks"] == 1 and out["incomplete_tasks"] == 1
    assert out["void_runs_by_server"] == {"strix": 3} and sum(out["void_runs_by_arm"].values()) == 3
    assert out["co_primaries"]["A-P"]["mean"] == 1.0


def test_early_stop_fires_after_50_complete_tasks_with_a_below_p_and_drops_a(mods, tmp_path):
    report, plan, run = mods
    ids = [f"t{i:03d}" for i in range(60)]

    def worse(spec):  # A never solves, P always does: A minus P is -1 on every task
        return {"resolved": spec.arm is not plan.Arm.A}

    result = run.run_phase(ids, phase(run, plan, tmp_path, worse))
    assert (tmp_path / "early_stop.json").is_file()
    assert result["finished"] == 60  # tasks after the stop run P and C only
    later = [r for r in run.graded_runs(tmp_path) if r["arm"] == "A"]
    assert len({r["instance_id"] for r in later}) == 50  # A stopped at the first 50 complete tasks
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    assert report.report(tmp_path, ids, arms)["early_stopped"] is True


def test_no_early_stop_when_a_is_not_wholly_below_p(mods, tmp_path):
    _, plan, run = mods
    ids = [f"t{i:03d}" for i in range(55)]
    run.run_phase(ids, phase(run, plan, tmp_path, lambda spec: {"resolved": True}))
    assert not (tmp_path / "early_stop.json").is_file()


def test_cutoff_is_pacific_standard_time_after_the_dst_change(mods):
    _, plan, _ = mods
    assert plan.CUTOFF.utcoffset().total_seconds() == -8 * 3600  # 2026-11-01 18:00 PST
