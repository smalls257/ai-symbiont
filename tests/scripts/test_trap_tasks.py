"""Constructed demo trap tasks: gradable rows; screens and checks use the row's own image."""

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION = ROOT / "scripts" / "calibration"
TASKS_FILE = ROOT / "demo_tasks" / "trap_tasks.toml"
LEDGERLINE = ROOT / "demo_tasks" / "ledgerline"
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
)


def load(monkeypatch, name):
    for stub in STUBBED:
        monkeypatch.setitem(sys.modules, stub, MagicMock())
    monkeypatch.syspath_prepend(str(CALIBRATION))
    spec = importlib.util.spec_from_file_location(f"trap_{name}", CALIBRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def new_files(patch):
    return set(re.findall(r"^\+\+\+ b/(\S+)", patch, flags=re.MULTILINE))


@pytest.mark.periphery
def test_every_task_builds_a_gradable_row(monkeypatch):
    rows = load(monkeypatch, "trap_rows").load_trap_rows(TASKS_FILE)
    assert [row["image"] for row in rows] == [f"symbiont-trap-{n}" for n in (1, 2, 3, 4)]
    for row in rows:
        assert row["label"] == "constructed demo task"
        assert set(row["lesson"]) == {"happened", "resolved", "check"}
        assert ("naive_patch" in row) != ("naive_command" in row)
        hidden = new_files(row["test_patch"])
        for test_id in row["FAIL_TO_PASS"] + row["PASS_TO_PASS"]:
            path = test_id.split("::")[0]
            assert " " not in test_id, test_id  # the grader's summary regex reads \S+::\S+
            assert path in hidden or (LEDGERLINE / path).is_file(), test_id
        assert all(path.startswith("tests/") for path in hidden)


@pytest.mark.periphery
def test_trap_scaffolding_of_other_tasks_is_dropped(monkeypatch):
    rows = {r["instance_id"]: r for r in load(monkeypatch, "trap_rows").load_trap_rows(TASKS_FILE)}
    assert "tests/soak" not in rows["ledgerline-trap-1-slow-suite"]["drop_paths"]
    assert "tests/rates" not in rows["ledgerline-trap-3-env-fixture"]["drop_paths"]
    assert (
        "LEDGERLINE_FIXTURES="
        in rows["ledgerline-trap-3-env-fixture"]["install_config"]["test_cmd"]
    )


@pytest.mark.periphery
def test_a_task_without_its_lesson_check_is_refused(monkeypatch, tmp_path):
    trap_rows = load(monkeypatch, "trap_rows")
    spec = TASKS_FILE.read_text().replace('check = "In ledgerline', 'not_check = "In ledgerline')
    broken = tmp_path / "trap_tasks.toml"
    broken.write_text(spec)
    (tmp_path / "tasks").symlink_to(TASKS_FILE.parent / "tasks")
    with pytest.raises(trap_rows.TrapTaskError, match="ledgerline-trap-1-slow-suite.*lesson.check"):
        trap_rows.load_trap_rows(broken)


@pytest.mark.periphery
def test_a_task_with_two_naive_actions_is_refused(monkeypatch, tmp_path):
    trap_rows = load(monkeypatch, "trap_rows")
    folder = tmp_path / "tasks" / "x"
    folder.mkdir(parents=True)
    for name in ("gold.patch", "hidden_test.patch", "naive.patch"):
        (folder / name).write_text("diff\n")
    task = {
        "instance_id": "x",
        "patch_dir": "tasks/x",
        "image": "i",
        "trap": "t",
        "drop_paths": ["a"],
        "problem_statement": "p",
        "FAIL_TO_PASS": ["t.py::a"],
        "PASS_TO_PASS": ["t.py::b"],
        "lesson": {"happened": "h", "resolved": "r", "check": "c"},
        "naive_command": "pytest",
    }
    with pytest.raises(trap_rows.TrapTaskError, match="exactly one"):
        trap_rows.trap_row(task, {"test_cmd": "pytest"}, tmp_path)


def test_image_build_drops_the_other_traps(monkeypatch):
    build = load(monkeypatch, "build_trap_images")
    row = {"image": "symbiont-trap-9", "instance_id": "x", "label": "constructed demo task"}
    command = build.build_command(row | {"drop_paths": ["tests/soak", "tests/rates"]}, "ctx", "df")
    assert command[command.index("-t") + 1] == "symbiont-trap-9"
    assert "DROP_PATHS=tests/soak tests/rates" in command


def test_a_naive_patch_that_does_not_apply_proves_nothing(monkeypatch):
    validate = load(monkeypatch, "validate_traps")
    unapplied = SimpleNamespace(
        resolved=False, patch_applied=False, f2p_passed=0, f2p_total=1, p2p_passed=0, p2p_total=1
    )
    monkeypatch.setattr(validate, "grade", lambda *args, **kwargs: unapplied)
    verdict = validate.naive_verdict({"image": "i", "naive_patch": "diff"})
    assert verdict["bites"] is False


def test_a_screen_grades_in_the_task_image_without_prepare(monkeypatch, tmp_path):
    screen = load(monkeypatch, "screen_traps")
    graded = {}

    def fake_grade(image, row, patch, *, prepare):
        graded.update(image=image, patch=patch, prepare=prepare)
        return SimpleNamespace(
            resolved=True, patch_applied=True, f2p_passed=1, f2p_total=1, p2p_passed=2, p2p_total=2
        )

    monkeypatch.setattr(screen, "attempt", lambda row, setting, traj, rec: "diff")
    monkeypatch.setattr(screen, "grade", fake_grade)
    row = {"instance_id": "x", "image": "symbiont-trap-2", "label": "constructed demo task"}
    rec = screen.screen_once(row, 1, screen.Setting("low", 5, 60), tmp_path)
    assert graded == {"image": "symbiont-trap-2", "patch": "diff", "prepare": False}
    assert rec["resolved"] is True
    assert rec["image"] == "symbiont-trap-2"
