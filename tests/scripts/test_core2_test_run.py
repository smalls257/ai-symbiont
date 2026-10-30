"""Core D2 runner with a fake adapter: back-to-back arms, seeds, voids, drops, cutoff, resume."""

import json
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
    import core2_test_plan
    import core2_test_run

    yield core2_test_plan, core2_test_run
    for name in ("core2_test_plan", "core2_test_run"):
        sys.modules.pop(name, None)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def phase_of(run, tmp_path, executor, hour=9, limit=None):
    plan = sys.modules["core2_test_plan"]
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    when = lambda: datetime(2026, 10, 31, hour, 0, tzinfo=PT)  # noqa: E731
    return run.Phase(executor, tmp_path, arms, when, limit)


def test_dry_run_on_one_task_with_a_fake_adapter(mods, tmp_path):
    plan, run = mods
    calls = []

    def fake_adapter(spec):
        calls.append(spec)
        return {"resolved": spec.arm is plan.Arm.A, "error_kind": None}

    ids = ["x1", "x2", "x3"]
    result = run.run_phase(ids, phase_of(run, tmp_path, fake_adapter, limit=1))
    assert result == {"started": 1, "finished": 1, "dropped": 0}
    first = plan.task_order(ids)[0]
    assert {c.task for c in calls} == {first} and len(calls) == 6  # all arms, one task
    recs = rows(tmp_path / "runs.jsonl")
    assert [r["seed"] for r in recs] == [c.seed for c in calls]  # seeds ride with every record
    assert all(r["temperature"] == 0.6 and r["instance_id"] == first for r in recs)
    entry = run.dry_plan(ids, frozenset({plan.Arm.P}), 1)[0]
    assert entry["task"] == first
    assert entry["seed"] == plan.run_seed(first, plan.Arm.P, entry["run"])


def test_a_void_run_is_rerun_and_a_task_that_stays_void_is_dropped(mods, tmp_path):
    plan, run = mods
    attempts = []

    def flaky(spec):
        attempts.append(spec)
        return {"resolved": None, "error_kind": "infra"}  # a failed scrub is infra: void

    result = run.run_phase(["only"], phase_of(run, tmp_path, flaky))
    assert result == {"started": 1, "finished": 0, "dropped": 1}
    assert len(attempts) == run.VOID_RERUNS + 1  # then no later arm starts
    assert len(rows(tmp_path / "voids.jsonl")) == run.VOID_RERUNS + 1
    assert rows(tmp_path / "dropped.jsonl")[0]["reason"] == "infra"
    assert rows(tmp_path / "runs.jsonl") == []
    again = run.run_phase(["only"], phase_of(run, tmp_path, flaky))
    assert again["started"] == 0  # a dropped task is not retried on resume


def test_no_task_starts_at_the_cutoff_and_a_resume_skips_graded_runs(mods, tmp_path):
    plan, run = mods
    ok = lambda spec: {"resolved": True, "error_kind": None}  # noqa: E731
    late = run.run_phase(["a"], phase_of(run, tmp_path, ok, hour=18))  # Oct 31 18:00 is before
    assert late["started"] == 1
    plan_cut = datetime(2026, 11, 1, 18, 0, tzinfo=PT)
    stopped = run.Phase(ok, tmp_path / "x", frozenset({plan.Arm.P}), lambda: plan_cut)
    assert run.run_phase(["a"], stopped)["started"] == 0
    calls = []
    run.run_phase(["a"], phase_of(run, tmp_path, lambda s: calls.append(s) or {"resolved": True}))
    assert calls == []  # every run already graded


def test_the_w_arm_has_no_executor_yet_and_says_so(mods):
    plan, _ = mods
    sys.path.insert(0, str(ROUTEB))
    import core2_test_executors

    with pytest.raises(NotImplementedError, match="worked examples"):
        core2_test_executors.arm_model({"models": {}}, plan.Arm.W)
    with pytest.raises(KeyError):
        core2_test_executors.arm_model({"models": {"P": "p"}}, plan.Arm.A)
    sys.modules.pop("core2_test_executors", None)
