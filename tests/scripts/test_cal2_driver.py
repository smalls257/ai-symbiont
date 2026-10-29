"""CAL2: every candidate gets 3 runs at the launcher's caps, bands and strata, request timeout."""

import importlib.util
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"


@dataclass(frozen=True)
class Setting:
    reasoning: str
    step_limit: int
    wall_limit_s: int
    adapter_id: int | None = None


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
    for name in ("staged", "staged_summary", "screen_rules", "lesson_arm", "cal2"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location("cal2_under_test", CALIBRATION / "cal2.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def make_workdir(tmp_path, n_tasks=6):
    (tmp_path / "data").mkdir(exist_ok=True)
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
    old = {  # old-cap evidence: id -> list of (resolved, exit_status)
        "task00": [(True, "Submitted"), (True, "Submitted"), (True, "Submitted")],  # above band
        "task01": [(True, "Submitted")],  # tier 0
        "task02": [(False, "LimitsExceeded")],  # tier 1
        "task03": [(False, "Submitted")],  # tier 2
        "task04": [(True, "Submitted"), (False, "Submitted")],  # tier 0
        "task05": [(False, "LimitsExceeded")],  # tier 1
    }
    for name, members in (("one", ids[:3]), ("two", ids[3:])):
        lines = [
            json.dumps({"instance_id": iid, "resolved": r, "exit_status": e})
            for iid in members
            for r, e in old[iid]
        ]
        (tmp_path / f"{name}.jsonl").write_text("".join(line + "\n" for line in lines))
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


def test_band_needs_two_runs_then_splits_hard_band_easy(monkeypatch):
    cal2 = load_cal2(monkeypatch)

    def runs(*solved):
        return [{"run": n, "resolved": s} for n, s in enumerate(solved, 1)]

    assert cal2.band_of_candidate(runs(True)) == "pending"
    assert cal2.band_of_candidate(runs(False, False)) == "too_hard"
    assert cal2.band_of_candidate(runs(True, True)) == "too_easy"
    assert cal2.band_of_candidate(runs(True, False)) == "in_band"
    assert cal2.band_of_candidate(runs(False, True, False)) == "in_band"
    assert [cal2.is_complete(runs(*r)) for r in ([True], [True, True], [True, False])] == [
        False,
        True,
        False,
    ]
    assert cal2.is_complete(runs(True, False, False))


def test_priority_puts_solved_then_cut_off_then_rest_and_skips_above_band(monkeypatch, tmp_path):
    cal2 = load_cal2(monkeypatch)
    workdir = make_workdir(tmp_path)
    order, skipped = cal2.priority_order(cal2.prior_records(workdir, ["one.jsonl", "two.jsonl"]))
    assert skipped == ["task00"]
    assert order == ["task01", "task04", "task02", "task05", "task03"]


def test_stop_rule_needs_target_over_enough_strata_or_a_barren_streak(monkeypatch):
    cal2 = load_cal2(monkeypatch)
    one_stratum = [("a", "in_band")] * cal2.TARGET_IN_BAND
    assert cal2.stop_reason(one_stratum) is None
    spread = one_stratum[:-2] + [("b", "in_band"), ("c", "in_band")]
    assert "strata" in cal2.stop_reason(spread)
    barren = [("a", "in_band")] + [("a", "too_hard")] * cal2.BARREN_LIMIT
    assert "in a row" in cal2.stop_reason(barren)
    assert cal2.stop_reason(barren[:-1]) is None


def test_two_runs_decide_unless_they_split_and_a_split_gets_run_three(monkeypatch, tmp_path):
    def solves(iid, run):
        return {"task01": True, "task02": run == 1}.get(iid, False)  # easy, split, hard...

    summary, calls = run_driver(monkeypatch, tmp_path, solves)
    runs_of = {iid: [r for r, i, *_ in calls if i == iid] for iid in {i for _, i, *_ in calls}}
    assert runs_of["task01"] == [1, 2] and runs_of["task02"] == [1, 2, 3]
    assert runs_of["task03"] == [1, 2] and "task00" not in runs_of
    assert summary["skipped_above_band"] == ["task00"] and summary["status"] == "done"
    assert summary["band_counts"]["in_band"] == 1 and summary["band_counts"]["too_easy"] == 1


def test_the_driver_stops_starting_tasks_once_the_target_is_met(monkeypatch, tmp_path):
    run_once, calls = graded_run(lambda iid, run: run == 1)
    cal2 = load_cal2(monkeypatch, run_once)
    monkeypatch.setattr(cal2, "TARGET_IN_BAND", 1)
    monkeypatch.setattr(cal2, "MIN_STRATA", 1)
    args = cal2.parse_args(
        [str(make_workdir(tmp_path)), "--runs-dir", "out", "--candidates-log", "one.jsonl"]
        + ["--candidates-log", "two.jsonl", "--step-limit", "75"]
    )
    driver = cal2.CandidateDriver(args.workdir, args.runs_dir, args.logs)
    driver.low = cal2.settings_for("low", args)
    driver.run()
    summary = json.loads(driver.summary_path.read_text())
    assert "in band" in summary["stop_reason"] and summary["not_started"] >= 1


def test_a_restarted_driver_keeps_graded_runs_and_the_stop_verdict(monkeypatch, tmp_path):
    _, first = run_driver(monkeypatch, tmp_path, lambda iid, run: iid == "task01")
    _, second = run_driver(monkeypatch, tmp_path, lambda iid, run: iid == "task01")
    assert first and second == []


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


def test_fixed_runs_give_every_listed_task_exactly_n_runs_in_file_order(monkeypatch, tmp_path):
    run_once, calls = graded_run(lambda iid, run: run == 1)  # every task splits 1 of 2
    cal2 = load_cal2(monkeypatch, run_once)
    args = cal2.parse_args(
        [str(make_workdir(tmp_path)), "--runs-dir", "t2", "--candidates-log", "one.jsonl"]
        + ["--fixed-runs", "2", "--step-limit", "75"]
    )
    driver = cal2.CandidateDriver(args.workdir, args.runs_dir, args.logs, args.fixed_runs)
    driver.low = cal2.settings_for("low", args)
    driver.run()
    summary = json.loads(driver.summary_path.read_text())
    assert sorted(calls) == [(r, f"task0{n}", 75, 1800) for r in (1, 2) for n in range(3)]
    assert summary["status"] == "done" and summary["skipped_above_band"] == []
    assert summary["band_counts"]["in_band"] == 3


def lesson_driver(monkeypatch, tmp_path, lessons):
    run_once, calls = graded_run(lambda iid, run: True)
    seen = []

    def run_and_keep_statement(row, run, setting, stage, traj_dir):
        seen.append((row["instance_id"], row.get("problem_statement")))
        return run_once(row, run, setting, stage, traj_dir)

    cal2 = load_cal2(monkeypatch, run_and_keep_statement)
    workdir = make_workdir(tmp_path)
    rows = [{"instance_id": f"task0{n}", "problem_statement": f"bug {n}"} for n in range(6)]
    (workdir / "data/sqlglot_rows.json").write_text(json.dumps(rows))
    (workdir / "lessons.json").write_text(json.dumps(lessons))
    args = cal2.parse_args(
        [str(workdir), "--runs-dir", "p", "--candidates-log", "one.jsonl", "--fixed-runs", "1"]
        + ["--lessons", str(workdir / "lessons.json"), "--workers", "4"]
    )
    driver = cal2.CandidateDriver(args.workdir, args.runs_dir, args.logs, args.fixed_runs)
    driver.low, driver.workers = cal2.settings_for("low", args), args.workers
    return cal2, driver, seen


def test_lesson_arm_prepends_the_lesson_and_stamps_arm_and_hash_on_every_record(
    monkeypatch, tmp_path
):
    lessons = {f"task0{n}": f"  Edit file {n} first.  " for n in range(3)}
    cal2, driver, seen = lesson_driver(monkeypatch, tmp_path, lessons)
    driver.give_lessons(tmp_path / "lessons.json")
    driver.run()
    assert sorted(seen) == [(f"task0{n}", f"Edit file {n} first.\n\nbug {n}") for n in range(3)]
    logged = [json.loads(line) for line in driver.log.read_text().splitlines()]
    assert {rec["arm"] for rec in logged} == {"lesson"}
    assert {rec["lesson_sha"] for rec in logged} == {
        cal2.lesson_hash(f"Edit file {n} first.") for n in range(3)
    }
    summary = json.loads(driver.summary_path.read_text())
    assert summary["arm"] == "lesson" and len(summary["lesson_sha"]) == 3
    assert driver.workers == 4


def test_a_listed_task_without_a_lesson_raises_before_any_run(monkeypatch, tmp_path):
    lessons = {"task00": "Edit it.", "task01": "   "}  # task01 empty, task02 missing
    _, driver, seen = lesson_driver(monkeypatch, tmp_path, lessons)
    with pytest.raises(KeyError, match="2 tasks have no lesson"):
        driver.give_lessons(tmp_path / "lessons.json")
    assert seen == []


def test_without_lessons_every_record_is_the_plain_arm(monkeypatch, tmp_path):
    _, driver, seen = lesson_driver(monkeypatch, tmp_path, {})
    driver.run()
    assert [statement for _, statement in sorted(seen)] == ["bug 0", "bug 1", "bug 2"]
    logged = [json.loads(line) for line in driver.log.read_text().splitlines()]
    assert {(rec["arm"], rec["lesson_sha"]) for rec in logged} == {("plain", None)}


def test_adapter_option_puts_the_lora_on_every_model_call_and_plain_has_none(monkeypatch):
    runner = load_runner(monkeypatch)
    _, plain = runner.agent_config(runner.Setting("low", 50, 2700))
    _, personal = runner.agent_config(runner.Setting("low", 50, 2700, adapter_id=0))
    assert "extra_body" not in plain["model_kwargs"]
    assert personal["model_kwargs"]["extra_body"] == {"lora": [{"id": 0, "scale": 1}]}


def test_adapter_arm_is_stamped_on_every_record_and_cannot_mix_with_lessons(monkeypatch, tmp_path):
    cal2, driver, seen = lesson_driver(monkeypatch, tmp_path, {"task00": "Edit it."})
    args = cal2.parse_args(
        [str(tmp_path), "--runs-dir", "p", "--candidates-log", "one.jsonl"] + ["--adapter", "0"]
    )
    driver.use_adapter(args.adapter)
    driver.run()
    logged = [json.loads(line) for line in driver.log.read_text().splitlines()]
    assert {(rec["arm"], rec["adapter_id"]) for rec in logged} == {("personal_lora", 0)}
    assert [statement for _, statement in sorted(seen)] == ["bug 0", "bug 1", "bug 2"]
    (tmp_path / "m").mkdir()
    _, mixed, _ = lesson_driver(
        monkeypatch, tmp_path / "m", {"task00": "a", "task01": "b", "task02": "c"}
    )
    mixed.give_lessons(tmp_path / "m" / "lessons.json")
    with pytest.raises(ValueError, match="one arm per run"):
        mixed.use_adapter(0)
