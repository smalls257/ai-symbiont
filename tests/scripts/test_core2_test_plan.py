"""Core D2 plan: the prereg's seeds, orders, cutoff and interval, derived one way."""

import hashlib
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


@pytest.fixture
def plan(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    import core2_test_plan

    yield core2_test_plan
    sys.modules.pop("core2_test_plan", None)


def test_seed_is_the_first_8_hex_digits_of_sha256(plan):
    digest = hashlib.sha256(b"core2-d2:t1:A:2").hexdigest()
    assert plan.run_seed("t1", plan.Arm.A, 2) == int(digest[:8], 16)
    assert plan.run_seed("t1", plan.Arm.A, 1) != plan.run_seed("t1", plan.Arm.A, 2)


def test_task_order_is_sha256_of_the_order_prefix(plan):
    ids = [f"t{i}" for i in range(30)]
    expected = sorted(ids, key=lambda i: hashlib.sha256(f"core-d2-order:{i}".encode()).hexdigest())
    assert plan.task_order(ids) == expected


def test_w_is_the_first_50_in_selection_hash_order_not_run_order(plan):
    ids = [f"t{i}" for i in range(100)]
    w = plan.worked_example_tasks(ids)
    by_select = sorted(ids, key=lambda i: hashlib.sha256(f"core-d2:{i}".encode()).hexdigest())
    assert w == frozenset(by_select[:50]) and len(w) == 50
    assert w != frozenset(plan.task_order(ids)[:50])


def test_a_task_has_seven_runs_back_to_back_and_eight_on_a_w_task(plan):
    assert len(plan.runs_of_task("t", in_w=False)) == 6
    with_w = plan.runs_of_task("t", in_w=True)
    assert len(with_w) == 7 and (plan.Arm.W, 1) in with_w
    only_pac = plan.runs_of_task("t", in_w=True, arms=frozenset({plan.Arm.P, plan.Arm.A}))
    assert {arm for arm, _ in only_pac} == {plan.Arm.P, plan.Arm.A}


def test_cutoff_is_sunday_1800_pacific(plan):
    pt = ZoneInfo("America/Los_Angeles")
    assert plan.may_start_task(datetime(2026, 11, 1, 17, 59, tzinfo=pt))
    assert not plan.may_start_task(datetime(2026, 11, 1, 18, 0, tzinfo=pt))
    assert plan.BOOTSTRAP_SEED == 20261101 and plan.BOOTSTRAP_RESAMPLES == 10_000


def records(plan, tasks, rates):
    out = []
    for task in tasks:
        for arm, run in plan.runs_of_task(task, in_w=False):
            out.append({"instance_id": task, "arm": str(arm), "run": run,
                        "resolved": rates[str(arm)](task)})  # fmt: skip
    return out


def test_complete_tasks_need_every_planned_run_graded(plan):
    tasks = ["a", "b"]
    recs = records(plan, tasks, {"P": lambda t: False, "A": lambda t: True, "C": lambda t: False})
    recs = [r for r in recs if not (r["instance_id"] == "b" and r["arm"] == "C" and r["run"] == 2)]
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    assert plan.complete_tasks(recs, tasks, arms) == ["a"]
    recs.append({"instance_id": "b", "arm": "C", "run": 2, "resolved": None})
    assert plan.complete_tasks(recs, tasks, arms) == ["a"]  # a void run does not complete a task


def test_both_lower_bounds_must_clear_zero(plan):
    tasks = [f"t{i}" for i in range(40)]
    gain = {"P": lambda t: False, "A": lambda t: True, "C": lambda t: False}
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    result = plan.co_primaries(records(plan, tasks, gain), tasks, arms)
    assert plan.claim_holds(result)
    same = {"P": lambda t: False, "A": lambda t: True, "C": lambda t: True}
    assert not plan.claim_holds(plan.co_primaries(records(plan, tasks, same), tasks, arms))


def test_bootstrap_is_seeded_and_reproducible(plan):
    diffs = [0.5, 0.0, -0.5, 0.5, 0.0, 0.5, 0.0, 0.0]
    first = plan.bootstrap_ci(diffs)
    assert first == plan.bootstrap_ci(diffs)
    assert first[1] <= first[0] <= first[2]
    assert first != plan.bootstrap_ci(diffs, random.Random(1))


def test_early_stop_needs_half_the_tasks_and_an_interval_wholly_below_zero(plan):
    assert plan.stops_early((-0.1, -0.2, -0.01), planned=100, complete=50)
    assert not plan.stops_early((-0.1, -0.2, -0.01), planned=100, complete=49)
    assert not plan.stops_early((-0.1, -0.2, 0.05), planned=100, complete=60)
