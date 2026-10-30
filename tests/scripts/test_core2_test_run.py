"""Core D2 runner with a fake adapter: one server per task, claims, voids, returns, cutoff."""

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
    for name in ("core2_test_plan", "core2_test_run", "core2_test_claims"):
        sys.modules.pop(name, None)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def make_phase(run, out, executor, **extra):
    plan = sys.modules["core2_test_plan"]
    arms = frozenset({plan.Arm.P, plan.Arm.A, plan.Arm.C})
    when = extra.pop("now", lambda: datetime(2026, 10, 31, 9, 0, tzinfo=PT))
    return run.Phase(executor, out, arms, when, extra.pop("server", "strix"), **extra)


def test_dry_run_on_one_task_with_a_fake_adapter(mods, tmp_path):
    plan, run = mods
    calls = []

    def fake_adapter(spec):
        calls.append(spec)
        return {"resolved": spec.arm is plan.Arm.A, "error_kind": None}

    ids = ["x1", "x2", "x3"]
    result = run.run_phase(ids, make_phase(run, tmp_path, fake_adapter, limit=1))
    assert result["finished"] == 1 and result["dropped"] == 0
    first = plan.task_order(ids)[0]
    assert {c.task for c in calls} == {first} and len(calls) == 6  # all arms, one task
    recs = rows(tmp_path / "runs.jsonl")
    assert {r["server"] for r in recs} == {"strix"} and len({r["block"] for r in recs}) == 1
    assert [r["seed"] for r in recs] == [c.seed for c in calls]
    entry = run.dry_plan(ids, frozenset({plan.Arm.P}), 1)[0]
    assert entry["seed"] == plan.run_seed(first, plan.Arm.P, entry["run"])


def test_two_servers_share_one_order_without_overlap(mods, tmp_path):
    plan, run = mods
    ok = lambda spec: {"resolved": True, "error_kind": None}  # noqa: E731
    ids = ["a", "b", "c", "d"]
    run.run_phase(ids, make_phase(run, tmp_path, ok, server="strix", limit=2))
    run.run_phase(ids, make_phase(run, tmp_path, ok, server="desk", limit=2))
    done = rows(tmp_path / "runs.jsonl")
    servers_of = {}
    for rec in done:
        servers_of.setdefault(rec["instance_id"], set()).add(rec["server"])
    assert sorted(servers_of) == ids and all(len(v) == 1 for v in servers_of.values())


def test_a_task_that_stays_void_on_a_healthy_server_is_dropped(mods, tmp_path):
    _, run = mods
    attempts = []

    def flaky(spec):
        attempts.append(spec)
        return {"resolved": None, "error_kind": "infra"}

    result = run.run_phase(["only"], make_phase(run, tmp_path, flaky))
    assert result["dropped"] == 1 and len(attempts) == run.VOID_RERUNS + 1
    assert rows(tmp_path / "dropped.jsonl")[0]["reason"] == "infra"
    assert run.graded_runs(tmp_path) == []
    again = run.run_phase(["only"], make_phase(run, tmp_path, flaky))
    assert again["finished"] == 0 and len(attempts) == run.VOID_RERUNS + 1  # not retried


def test_a_server_that_stops_answering_gives_the_task_back_whole(mods, tmp_path):
    plan, run = mods
    health = iter([True, False])  # up at the claim, down when a run stays void

    def executor(spec):
        done = len(rows(tmp_path / "runs.jsonl"))
        return {"resolved": True} if done < 1 else {"resolved": None, "error_kind": "infra"}

    state = {"up": True}
    phase = make_phase(run, tmp_path, executor, limit=1, healthy=lambda: next(health, False))
    result = run.run_phase(["t"], phase)
    assert result["returned"] == 1 and result["finished"] == 0
    assert run.graded_runs(tmp_path) == []  # the half-run block is voided, never scored
    assert rows(tmp_path / "voided_blocks.jsonl")[0]["reason"] == "server stopped answering"
    ok = lambda spec: {"resolved": True}  # noqa: E731
    other = make_phase(run, tmp_path, ok, server="desk", limit=1)
    assert run.run_phase(["t"], other)["finished"] == 1  # another server runs all six arms
    assert len(run.graded_runs(tmp_path)) == 6 and state["up"]


def test_a_restarted_worker_voids_its_unfinished_block(mods, tmp_path):
    plan, run = mods
    book = sys.modules["core2_test_claims"].ClaimBook(tmp_path / "claims.jsonl")
    task, block = book.claim_next(["t"], set(), "strix-1")  # claimed, then the process died
    ok = lambda spec: {"resolved": True}  # noqa: E731
    result = run.run_phase(["t"], make_phase(run, tmp_path, ok, limit=1))
    assert result["released_stale"] == 1 and result["finished"] == 1
    assert block in {r["block"] for r in rows(tmp_path / "voided_blocks.jsonl")}


def test_no_task_is_claimed_at_the_cutoff(mods, tmp_path):
    _, run = mods
    cut = lambda: datetime(2026, 11, 1, 18, 0, tzinfo=PT)  # noqa: E731
    ok = lambda spec: {"resolved": True}  # noqa: E731
    assert run.run_phase(["a"], make_phase(run, tmp_path, ok, now=cut))["finished"] == 0


def test_the_w_arm_is_plain_with_examples_and_other_names_must_exist(mods):
    plan, _ = mods
    sys.path.insert(0, str(ROUTEB))
    import core2_test_executors as ex

    server = {"models": {"P": "p", "A": "a", "C": "c"}}
    assert ex.arm_model(server, plan.Arm.W) == "openai/p"
    assert ex.arm_model(server, plan.Arm.A) == "openai/a"
    with pytest.raises(KeyError):
        ex.arm_model({"models": {"P": "p"}}, plan.Arm.A)
    sys.modules.pop("core2_test_executors", None)


def test_a_two_adapter_server_picks_the_lora_by_arm(mods):
    plan, _ = mods
    sys.path.insert(0, str(ROUTEB))
    import core2_test_executors as ex

    server = {"models": {"P": "m", "A": "m", "C": "m"}, "adapter_ids": {"A": 0, "C": 1}}
    assert [ex.arm_adapter_id(server, a) for a in (plan.Arm.P, plan.Arm.A, plan.Arm.C)] == [
        None,
        0,
        1,
    ]
    sys.modules.pop("core2_test_executors", None)
