"""CAL2: every candidate gets 3 runs at the launcher's caps, bands and strata, request timeout."""

import importlib.util
import json
import os
import sys
import types
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"
Setting = namedtuple("Setting", "reasoning step_limit wall_limit_s")


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop modules a test imported so one test's stubs never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load_cal2(monkeypatch, run_once=None):
    stub = types.ModuleType("run_calibration")
    stub.IMAGE, stub.MODEL, stub.Setting, stub.run_once = "image", "model", Setting, run_once
    monkeypatch.setitem(sys.modules, "run_calibration", stub)
    monkeypatch.syspath_prepend(str(CALIBRATION))
    for name in ("staged", "staged_summary", "screen_rules", "cal2"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location("cal2_under_test", CALIBRATION / "cal2.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def make_workdir(tmp_path, n_tasks=6):
    (tmp_path / "data").mkdir()
    ids = [f"task{n:02d}" for n in range(n_tasks)]
    pool = [
        {
            "instance_id": iid,
            "gold_changed_lines": n,
            "subsystem": "parser" if n % 2 else "dialect",
            "size_band": "small",
        }
        for n, iid in enumerate(ids)
    ]
    (tmp_path / "data/sqlglot_rows.json").write_text(
        json.dumps([{"instance_id": iid} for iid in ids])
    )
    (tmp_path / "data/pool.json").write_text(json.dumps({"pool": pool}))
    for name, members in (("one", ids[:4]), ("two", ids[2:])):  # overlap: ids deduplicated
        (tmp_path / f"{name}.jsonl").write_text(
            "".join(json.dumps({"instance_id": iid}) + "\n" for iid in members)
        )
    return tmp_path


def graded_run(solves):
    calls = []

    def run_once(row, run, setting, stage, traj_dir):
        calls.append((run, row["instance_id"], setting.step_limit, setting.wall_limit_s))
        return {
            "instance_id": row["instance_id"],
            "run": run,
            "reasoning": setting.reasoning,
            "step_limit": setting.step_limit,
            "stage": stage,
            "resolved": solves(row["instance_id"], run),
        }

    return run_once, calls


def run_driver(monkeypatch, tmp_path, solves):
    run_once, calls = graded_run(solves)
    cal2 = load_cal2(monkeypatch, run_once)
    args = cal2.parse_args(
        [str(make_workdir(tmp_path)), "--runs-dir", "out", "--candidates-log", "one.jsonl"]
        + ["--candidates-log", "two.jsonl", "--step-limit", "75", "--wall-limit-min", "25"]
    )
    driver = cal2.CandidateDriver(args.workdir, args.runs_dir, args.logs)
    driver.low = cal2.settings_for("low", args)
    driver.run()
    return json.loads(driver.summary_path.read_text()), calls


def test_band_waits_for_three_runs_then_splits_hard_band_easy(monkeypatch):
    cal2 = load_cal2(monkeypatch)

    def runs(*solved):
        return [{"run": n, "resolved": s} for n, s in enumerate(solved, 1)]

    assert cal2.band_of_candidate(runs(True, True)) == "pending"
    assert cal2.band_of_candidate(runs(False, False, False)) == "too_hard"
    assert cal2.band_of_candidate(runs(False, False, True)) == "in_band"
    assert cal2.band_of_candidate(runs(True, True, False)) == "in_band"
    assert cal2.band_of_candidate(runs(True, True, True)) == "too_easy"


def test_every_candidate_gets_three_runs_even_after_failing_run_one(monkeypatch, tmp_path):
    summary, calls = run_driver(
        monkeypatch, tmp_path, lambda iid, run: iid == "task00" and run == 3
    )
    assert summary["status"] == "done" and len(calls) == 6 * 3
    assert summary["band_counts"] == {"in_band": 1, "too_easy": 0, "too_hard": 5, "pending": 0}


def test_runs_go_round_by_round_under_the_launcher_caps(monkeypatch, tmp_path):
    _, calls = run_driver(monkeypatch, tmp_path, lambda iid, run: False)
    assert [run for run, *_ in calls] == sorted(run for run, *_ in calls)
    assert {(steps, wall) for _, _, steps, wall in calls} == {(75, 25 * 60)}


def test_summary_counts_bands_per_stratum_and_keeps_no_task_text(monkeypatch, tmp_path):
    summary, _ = run_driver(monkeypatch, tmp_path, lambda iid, run: iid == "task01")
    assert summary["per_stratum"]["parser/small"]["too_easy"] == 1
    assert summary["per_stratum"]["dialect/small"]["too_hard"] == 3
    assert {task["stratum"] for task in summary["tasks"]} == {"parser/small", "dialect/small"}


def test_a_candidate_missing_from_the_pool_raises(monkeypatch):
    cal2 = load_cal2(monkeypatch)
    with pytest.raises(KeyError, match="not in the pool"):
        cal2.stratum_labels([], ["ghost"])


def test_caps_default_to_the_original_50_steps_and_30_minutes(monkeypatch):
    cal2 = load_cal2(monkeypatch)
    args = cal2.parse_args(["w", "--runs-dir", "o", "--candidates-log", "l"])
    assert (args.step_limit, args.wall_limit_min) == (50, 30)


class LitellmTimeoutError(Exception):
    pass


def load_runner(monkeypatch):
    exceptions = types.SimpleNamespace(
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        Timeout=LitellmTimeoutError,
        ServiceUnavailableError=type("ServiceUnavailableError", (Exception,), {}),
        InternalServerError=type("InternalServerError", (Exception,), {}),
        ContextWindowExceededError=type("ContextWindowExceededError", (Exception,), {}),
    )
    yaml = types.SimpleNamespace(
        safe_load=lambda text: {"agent": {"system_template": "s"}, "model": {}}
    )
    stubs = {
        "litellm": types.SimpleNamespace(exceptions=exceptions),
        "litellm.exceptions": exceptions,
        "yaml": yaml,
    }
    for name in (
        "minisweagent",
        "minisweagent.agents",
        "minisweagent.agents.default",
        "minisweagent.config",
        "minisweagent.environments",
        "minisweagent.environments.docker",
        "minisweagent.models",
        "minisweagent.models.litellm_model",
    ):
        stubs[name] = MagicMock()
    for name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, name, stub)
    monkeypatch.syspath_prepend(str(CALIBRATION))
    monkeypatch.setenv("SYMBIONT_GLIMMER_URL", "http://glimmer.invalid")
    spec = importlib.util.spec_from_file_location(
        "run_calibration_timeout_test", CALIBRATION / "run_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_a_stalled_request_is_bounded_by_a_timeout_and_few_retries(monkeypatch):
    monkeypatch.delenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", raising=False)
    runner = load_runner(monkeypatch)
    _, model = runner.agent_config(runner.Setting("low", 75, 1800))
    assert model["model_kwargs"]["timeout"] == runner.REQUEST_TIMEOUT_S <= 600
    assert int(os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"]) == runner.MODEL_RETRY_ATTEMPTS
    assert runner.MODEL_RETRY_ATTEMPTS <= 2


def test_a_request_timeout_is_recorded_as_a_model_api_error_not_raised(monkeypatch):
    runner = load_runner(monkeypatch)
    agent = MagicMock()
    agent.run.side_effect = LitellmTimeoutError("request timed out")
    rec: dict = {}
    info = runner._run_agent(agent, {"problem_statement": "x"}, rec)
    assert rec["error_kind"] == "model_api" and "LitellmTimeoutError" in rec["error"]
    assert info["submission"] == ""
