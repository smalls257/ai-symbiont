"""Pure helpers of the calibration scripts: pytest summary parsing, grading, image comparison."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so the stubs of one test never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(CALIBRATION))
    spec = importlib.util.spec_from_file_location(f"calib_{name}", CALIBRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROW = {"FAIL_TO_PASS": ["t.py::a"], "PASS_TO_PASS": ["t.py::b"]}


def test_summary_lines_of_both_pytest_formats_are_parsed(monkeypatch):
    taskenv = load(monkeypatch, "taskenv")
    output = "PASSED t.py::a\nt.py::b FAILED\nFAILED t.py::c - boom\nnoise"
    assert taskenv.parse_pytest_summary(output) == {
        "t.py::a": "PASSED",
        "t.py::b": "FAILED",
        "t.py::c": "FAILED",
    }


def test_a_task_is_resolved_only_when_every_listed_test_passes(monkeypatch):
    taskenv = load(monkeypatch, "taskenv")
    passed = {"t.py::a": "PASSED", "t.py::b": "PASSED"}
    assert taskenv.score(ROW, passed).resolved
    assert not taskenv.score(ROW, {"t.py::a": "PASSED"}).resolved
    assert taskenv.score(ROW, {"t.py::a": "PASSED"}).status["t.py::b"] == "MISSING"
    assert not taskenv.score(ROW, passed, patch_applied=False).resolved


def test_prepare_script_is_valid_shell_and_pins_the_base_commit(monkeypatch):
    taskenv = load(monkeypatch, "taskenv")
    script = taskenv.prepare_script("abc123")
    assert 'test "$(git rev-parse HEAD)" = "abc123"' in script
    bash = shutil.which("bash")
    result = subprocess.run([bash, "-n"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def grade_of(taskenv, status, resolved=True):
    return taskenv.Grade(resolved, True, 1, 1, 1, 1, status)


def test_status_diff_lists_only_tests_whose_status_changed(monkeypatch):
    verify = load(monkeypatch, "verify_disk")
    taskenv = sys.modules["taskenv"] if "taskenv" in sys.modules else load(monkeypatch, "taskenv")
    stock = grade_of(taskenv, {"a": "PASSED", "b": "FAILED"})
    shared = grade_of(taskenv, {"a": "PASSED"})
    assert verify.status_diff(stock, shared) == {"b": ("FAILED", None)}


def test_gold_must_resolve_in_the_shared_image_for_the_images_to_agree(monkeypatch):
    verify = load(monkeypatch, "verify_disk")
    taskenv = sys.modules["taskenv"]
    same = grade_of(taskenv, {"a": "PASSED"}, resolved=False)
    record = verify.compare_record("id", "gold", same, same)
    assert record["same"] and record["diff"] == {}
    assert not verify.patch_agrees(record, "gold", same)
    assert verify.patch_agrees(record, "empty", same)


@pytest.mark.parametrize("label", ["empty", "gold"])
def test_compare_record_drops_per_test_status_from_the_grades(monkeypatch, label):
    verify = load(monkeypatch, "verify_disk")
    taskenv = sys.modules["taskenv"]
    grade = grade_of(taskenv, {"a": "PASSED"})
    record = verify.compare_record("id", label, grade, grade)
    assert "status" not in record["stock"] and record["patch"] == label
