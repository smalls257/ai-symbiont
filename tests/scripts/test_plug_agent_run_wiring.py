"""PLUG-AGENT-1 runner rules: one requeue for a void run, a task that stays void drops from all
five runs, and a down judge stops the phase instead of becoming a none run."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
STUBS = (
    "minisweagent",
    "minisweagent.agents",
    "minisweagent.agents.default",
    "minisweagent.environments",
    "minisweagent.environments.docker",
    "plug_agent_env",
)


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    for name in STUBS:
        monkeypatch.setitem(sys.modules, name, type(sys)("stub"))
    sys.modules["plug_agent_env"].run_task = None
    import plug_agent_notes  # noqa: F401  imported so its module is the one the runner uses
    import plug_agent_run

    yield plug_agent_run
    for name in ("plug_agent_run", "plug_agent_notes", "plug_agent_store"):
        sys.modules.pop(name, None)


def fake_plan(tmp_path, runner):
    store = SimpleNamespace(candidates=(), removed_counts=lambda: [0, 0, 0])
    return SimpleNamespace(
        config={"void_requeue_cap": 1},
        out=tmp_path,
        mode=runner.Mode.LIVE,
        store=lambda task, row: store,
        source=lambda arm, row, store: arm,
    )


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def test_a_void_run_is_requeued_once_then_returns_none(runner):
    calls = []

    def always_void():
        calls.append(1)
        return {"resolved": None, "error_kind": "infra"}

    rec, voids = runner.run_until_graded(always_void, requeues=1)
    assert rec is None and len(voids) == 2 and len(calls) == 2
    answers = iter([{"resolved": None}, {"resolved": False}])
    rec, voids = runner.run_until_graded(lambda: next(answers), requeues=1)
    assert rec == {"resolved": False} and len(voids) == 1


def test_a_task_that_stays_void_is_dropped_from_all_five_runs(runner, monkeypatch, tmp_path):
    plan = fake_plan(tmp_path, runner)
    ran = []

    def run_task(row, arm, config, traj):
        ran.append(str(arm))
        void = len(ran) in (3, 4)  # the third arm is void on both tries
        return {"instance_id": "t", "arm": str(arm), "resolved": None if void else True}

    monkeypatch.setattr(runner, "run_task", run_task)
    runner.run_arms(plan, "t", {}, set())
    assert len(ran) == 4  # two graded arms, then the void arm twice; the rest never start
    assert [r["instance_id"] for r in lines(tmp_path / "dropped.jsonl")] == ["t"]
    assert len(lines(tmp_path / "voids.jsonl")) == 2
    assert runner.dropped_tasks(tmp_path) == {"t"}
    assert runner.scored_records(tmp_path) == []  # the two graded arms are excluded too


def test_a_down_judge_stops_the_phase_not_the_arm(runner, monkeypatch, tmp_path):
    notes = sys.modules["plug_agent_notes"]
    plan = fake_plan(tmp_path, runner)

    def run_task(row, arm, config, traj):
        raise notes.JudgeDownError("judge at x did not answer")

    monkeypatch.setattr(runner, "run_task", run_task)
    with pytest.raises(notes.JudgeDownError):
        runner.run_arms(plan, "t", {}, set())
    assert lines(tmp_path / "runs.jsonl") == [] and lines(tmp_path / "voids.jsonl") == []
