"""PLUG-AGENT-2 branch points: where the first known mistake is, how an arm resumes, and the
driver's pins."""

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_branchpoint import find_branch_point, repeated_after, resume_messages  # noqa: E402
from plug_agent2_keys import key_of  # noqa: E402
from plug_agent_notes import failure_of  # noqa: E402

FAIL = "<returncode>1</returncode>\n<output>\nE   ValueError: bad\n</output>"
PASS = "<returncode>0</returncode>\n<output>\nok\n</output>"


def ask(*commands: str) -> dict:
    actions = [{"command": command} for command in commands]
    return {"role": "assistant", "content": "", "extra": {"actions": actions}}


def answer(output: str) -> dict:
    return {"role": "tool", "content": output}


def known_for(command: str) -> frozenset:
    failure = failure_of(command, 1, FAIL)
    assert failure is not None and key_of(failure) is not None
    return frozenset({key_of(failure)})


def test_no_branch_point_without_a_known_failure():
    history = [ask("pytest t/a.py"), answer(PASS)]
    assert find_branch_point(history, known_for("pytest t/a.py")) is None


def test_branch_point_is_the_first_known_failure_with_the_history_up_to_it():
    history = [
        ask("ls"),
        answer(PASS),
        ask("pytest t/a.py"),
        answer(FAIL),
        ask("pytest t/a.py"),
        answer(FAIL),
    ]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    assert (point.model_calls, point.failing_observation, len(point.messages)) == (2, 3, 4)


def test_a_step_with_two_actions_is_cut_after_both_observations():
    known = known_for("pytest t/a.py")
    history = [ask("pytest t/a.py", "ls"), answer(FAIL)]
    assert find_branch_point(history, known) is None  # the second observation is not in yet
    point = find_branch_point([*history, answer(PASS)], known)
    assert point is not None and len(point.messages) == 3 and point.failing_observation == 1


def test_resume_puts_the_note_under_the_failing_observation_without_touching_the_original():
    history = [ask("pytest t/a.py"), answer(FAIL)]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    with_note = resume_messages(point, "NOTE TEXT")
    without = resume_messages(point, None)
    assert "NOTE TEXT" in with_note[1]["content"] and "NOTE TEXT" not in without[1]["content"]
    assert without == list(point.messages) and "NOTE" not in history[1]["content"]


def test_repeat_is_the_same_key_failing_after_the_shared_history():
    history = [ask("pytest t/a.py"), answer(FAIL)]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    assert repeated_after([*history, ask("pytest t/a.py"), answer(FAIL)], point) is True
    assert repeated_after([*history, ask("pytest t/a.py"), answer(PASS)], point) is False


def stubbed_point(monkeypatch: pytest.MonkeyPatch):
    """plug_agent2_point with the heavy branch module replaced by a stub."""
    stub = ModuleType("plug_agent2_branch")
    for name in ("Continuation", "FidelityError", "image_tag", "run_continuation", "run_prefix"):
        setattr(stub, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "plug_agent2_branch", stub)
    monkeypatch.delitem(sys.modules, "plug_agent2_point", raising=False)
    import plug_agent2_point  # noqa: PLC0415

    return plug_agent2_point


def test_a_changed_pinned_file_stops_the_driver_before_anything_runs(monkeypatch, tmp_path):
    driver = stubbed_point(monkeypatch)
    labels = tmp_path / "labels.json"
    labels.write_text("{}")
    config = tmp_path / "config.json"
    pins = {field: driver.sha256_of(path) for field, path in driver.PINS.items()}
    config.write_text(json.dumps(pins | {"labels_sha256": driver.sha256_of(labels)}))
    assert driver.checked_config(config, labels)["labels_sha256"]
    labels.write_text('{"changed": 1}')
    with pytest.raises(driver.ConfigPinError):
        driver.checked_config(config, labels)
