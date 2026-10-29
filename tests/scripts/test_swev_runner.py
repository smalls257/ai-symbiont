"""Django runner: arm endpoints, official grading outcomes, paired schedule, resume, block."""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SWEV = Path(__file__).resolve().parents[2] / "scripts" / "swev"
CALIBRATION = SWEV.parent / "calibration"
STUBBED = (
    "yaml",
    "litellm",
    "litellm.exceptions",
    "minisweagent",
    "minisweagent.agents",
    "minisweagent.agents.default",
    "minisweagent.config",
    "minisweagent.environments",
    "minisweagent.environments.docker",
    "minisweagent.models",
    "minisweagent.models.litellm_model",
    "swebench",
    "swebench.harness",
    "swebench.harness.grading",
    "swebench.harness.run_evaluation",
    "swebench.harness.utils",
)
FRESH = ("taskenv", "run_calibration", "swev_env", "swev_run", "swev_driver", "swev_tasks")


@pytest.fixture
def mods(monkeypatch):
    for name in STUBBED:
        monkeypatch.setitem(sys.modules, name, MagicMock())
    sys.modules["swebench.harness.run_evaluation"].GIT_APPLY_CMDS = ["git apply", "patch"]
    for name in FRESH:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(CALIBRATION))
    monkeypatch.syspath_prepend(str(SWEV))
    loaded = {name: importlib.import_module(name) for name in ("swev_env", "swev_run")}
    loaded["swev_driver"] = importlib.import_module("swev_driver")
    yield loaded
    for name in FRESH:
        sys.modules.pop(name, None)


def test_personal_arm_never_falls_back_to_plain(mods, monkeypatch):
    run = mods["swev_run"]
    monkeypatch.setenv("SYMBIONT_GLIMMER_URL", "http://plain.invalid")
    monkeypatch.delenv("SYMBIONT_PERSONAL_GLIMMER_URL", raising=False)
    monkeypatch.setenv("SYMBIONT_PERSONAL_GLIMMER_MODEL", "openai/personal")
    with pytest.raises(SystemExit, match="SYMBIONT_PERSONAL_GLIMMER_URL"):
        run.endpoint(run.Arm.PERSONAL)
    monkeypatch.setenv("SYMBIONT_PERSONAL_GLIMMER_URL", "http://personal.invalid")
    assert run.endpoint(run.Arm.PERSONAL) == ("openai/personal", "http://personal.invalid")
    assert run.endpoint(run.Arm.PLAIN)[1] == "http://plain.invalid"


def test_scrub_keeps_only_head_history_and_checks_it(mods):
    script = mods["swev_env"].scrub_history_script()
    assert "update-ref -d" in script
    assert "gc -q --prune=now" in script
    assert script.rstrip().endswith('test "$(git rev-list --all --not HEAD | wc -l)" = 0')


class FakeBox:
    """Container stand-in: exit codes by command prefix, eval log fixed."""

    def __init__(self, apply_rc: int):
        self.apply_rc, self.ran = apply_rc, []

    def sh(self, script, *, timeout=600, check=True):
        self.ran.append(script)
        if script.startswith("cd /testbed && ") and script.endswith("/tmp/patch.diff"):
            return self.apply_rc, ""
        return 0, "test log"

    def stop(self):
        self.ran.append("stopped")


def _grade(mods, monkeypatch, report: dict, apply_rc: int = 0, patch: str = "diff"):
    env = mods["swev_env"]
    box = FakeBox(apply_rc)
    monkeypatch.setattr(env, "Container", lambda image, network: box)
    monkeypatch.setattr(env, "get_eval_report", lambda *a, **k: {"d-1": report})
    row = {"instance_id": "d-1", "image": "img", "eval_script": "#!/bin/bash"}
    return env.grade(row, patch), box


STATUS = {
    "FAIL_TO_PASS": {"success": ["a"], "failure": []},
    "PASS_TO_PASS": {"success": ["b", "c"], "failure": ["d"]},
}


def test_official_report_maps_to_outcome_and_counts(mods, monkeypatch):
    report = {"patch_successfully_applied": True, "resolved": False, "tests_status": STATUS}
    found, box = _grade(mods, monkeypatch, report)
    assert found.outcome == "unresolved"
    assert (found.f2p, found.p2p) == ((1, 1), (2, 3))
    assert box.ran[-1] == "stopped"


def test_patch_that_never_applies_is_an_outcome_not_an_error(mods, monkeypatch):
    found, box = _grade(mods, monkeypatch, {}, apply_rc=1)
    assert found.outcome == "patch_not_applied"
    assert not found.resolved
    assert not any("eval.sh" in cmd for cmd in box.ran)


def test_unparsed_test_output_raises_instead_of_counting_a_fail(mods, monkeypatch):
    report = {"patch_successfully_applied": False, "infra_failure_reason": "locale"}
    with pytest.raises(mods["swev_env"].ScorerError, match="no test results parsed"):
        _grade(mods, monkeypatch, report, patch="")


def test_schedule_is_task_major_so_a_stop_leaves_pairs(mods):
    drv, arm = mods["swev_driver"], mods["swev_run"].Arm
    jobs = drv.schedule(["t1", "t2"], "later", [arm.PLAIN, arm.PERSONAL], 2)
    seen = [(j.instance_id, j.slot.run, str(j.slot.arm)) for j in jobs]
    assert seen[:4] == [
        ("t1", 1, "plain"),
        ("t1", 1, "personal"),
        ("t1", 2, "plain"),
        ("t1", 2, "personal"),
    ]
    assert len(jobs) == 8


def _driver(mods, tmp_path, outcomes: list):
    drv, run = mods["swev_driver"], mods["swev_run"]
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data/django_rows.json").write_text(json.dumps([{"instance_id": "t1"}]))
    jobs = drv.schedule(["t1"], "history", [run.Arm.PLAIN], 2)
    setting = run.Setting("low", 50, 1800)

    def fake_run_once(row, slot, setting_, traj_dir):
        resolved = outcomes.pop(0)
        base = {"instance_id": row["instance_id"], "phase": slot.phase, "arm": str(slot.arm)}
        return base | {"run": slot.run, "step_limit": 50, "resolved": resolved, "error": "e"}

    drv.run_once = fake_run_once
    return drv.SwevDriver(tmp_path, tmp_path / "runs", jobs, setting)


def test_driver_resumes_and_summarizes_counts(mods, tmp_path):
    first = _driver(mods, tmp_path, [True, False])
    first.run()
    again = _driver(mods, tmp_path, [])  # nothing left to run: an extra run_once would IndexError
    again.run()
    summary = json.loads((tmp_path / "runs/swev-summary.json").read_text())
    assert summary["status"] == "done"
    assert summary["arms"]["plain"]["graded"] == 2
    assert summary["arms"]["plain"]["resolved"] == 1
    assert summary["tasks"] == [{"instance_id": "t1", "plain": [1, 2]}]


def test_driver_blocks_after_three_ungraded_in_a_row(mods, tmp_path):
    driver = _driver(mods, tmp_path, [None] * 6)  # the other worker may have one in flight
    driver.run()
    summary = json.loads((tmp_path / "runs/swev-summary.json").read_text())
    assert summary["status"] == "blocked"
    assert summary["arms"]["plain"]["graded"] == 0


def test_a_task_whose_environment_errors_on_every_test_is_not_gradeable(mods, monkeypatch):
    monkeypatch.syspath_prepend(str(SWEV))
    sys.modules.pop("validate_scorer", None)
    check = importlib.import_module("validate_scorer")
    grade, outcome = mods["swev_env"].Grade, mods["swev_env"].Outcome
    every_test_errors = grade(outcome.UNRESOLVED, f2p=(0, 3), p2p=(0, 40))
    healthy_base_tree = grade(outcome.UNRESOLVED, f2p=(0, 3), p2p=(40, 40))
    assert not check.grade_ok("none", every_test_errors)
    assert check.grade_ok("none", healthy_base_tree)
    assert not check.grade_ok("none", grade(outcome.UNRESOLVED))  # no test ran at all
    assert check.grade_ok("gold", grade(outcome.RESOLVED, f2p=(3, 3), p2p=(40, 40)))
    assert not check.grade_ok("gold", grade(outcome.UNRESOLVED, f2p=(2, 3), p2p=(40, 40)))
    sys.modules.pop("validate_scorer", None)
