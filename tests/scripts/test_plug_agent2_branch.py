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


TASK = {"role": "user", "content": "task text"}


def test_no_branch_point_without_a_known_failure():
    history = [TASK, ask("pytest t/a.py"), answer(PASS)]
    assert find_branch_point(history, known_for("pytest t/a.py")) is None


def test_branch_point_holds_the_history_before_the_turn_that_issued_the_first_known_failure():
    history = [
        TASK,
        ask("ls"),
        answer(PASS),
        ask("pytest t/a.py"),
        answer(FAIL),
        ask("pytest t/a.py"),
        answer(FAIL),
    ]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    assert list(point.messages) == history[:3] and point.model_calls == 1


def test_a_step_with_two_actions_is_cut_before_its_whole_turn_once_both_observations_are_in():
    known = known_for("pytest t/a.py")
    history = [TASK, ask("pytest t/a.py", "ls"), answer(FAIL)]
    assert find_branch_point(history, known) is None  # the second observation is not in yet
    point = find_branch_point([*history, answer(PASS)], known)
    assert point is not None and list(point.messages) == [TASK] and point.model_calls == 0


def test_resume_puts_the_note_under_the_last_message_without_touching_the_original():
    history = [TASK, ask("ls"), answer(PASS), ask("pytest t/a.py"), answer(FAIL)]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    with_note, without = resume_messages(point, "NOTE TEXT"), resume_messages(point, None)
    assert "NOTE TEXT" in with_note[-1]["content"] and "NOTE TEXT" not in without[-1]["content"]
    assert without == list(point.messages) and "NOTE" not in history[2]["content"]


def test_the_outcome_is_the_same_error_line_occurring_in_the_branch():
    history = [TASK, ask("pytest t/a.py"), answer(FAIL)]
    point = find_branch_point(history, known_for("pytest t/a.py"))
    assert point is not None
    start = list(point.messages)
    assert repeated_after([*start, ask("pytest t/a.py"), answer(FAIL)], point) is True
    assert repeated_after([*start, ask("pytest t/a.py"), answer(PASS)], point) is False
    assert (
        repeated_after(
            [*start, ask("ls"), answer(PASS), ask("pytest t/a.py"), answer(FAIL)], point, window=1
        )
        is False
    )


def stubbed_point(monkeypatch: pytest.MonkeyPatch):
    """plug_agent2_point with the heavy branch module replaced by a stub."""
    stub = ModuleType("plug_agent2_branch")
    for name in (
        "Continuation",
        "FidelityError",
        "ReplayMismatchError",
        "image_tag",
        "run_continuation",
        "run_prefix",
    ):
        setattr(stub, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "plug_agent2_branch", stub)
    monkeypatch.delitem(sys.modules, "plug_agent2_point", raising=False)
    import plug_agent2_point  # noqa: PLC0415

    return plug_agent2_point


def pinned_setup(driver, tmp_path):
    labels, pool = tmp_path / "labels.json", tmp_path / "pool.json"
    labels.write_text("{}")
    pool.write_text("{}")
    pins = {field: driver.sha256_of(path) for field, path in driver.PINS.items()}
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            pins
            | {
                "labels_sha256": driver.sha256_of(labels),
                "pool_summary_sha256": driver.sha256_of(pool),
            }
        )
    )
    return config, {"labels_sha256": labels, "pool_summary_sha256": pool}


def test_the_whole_config_and_each_pinned_file_must_match(monkeypatch, tmp_path):
    driver = stubbed_point(monkeypatch)
    config, pinned = pinned_setup(driver, tmp_path)
    expected = driver.sha256_of(config)
    assert driver.checked_config(config, expected, pinned)["labels_sha256"]
    with pytest.raises(driver.ConfigPinError):
        driver.checked_config(config, "0" * 64, pinned)  # the config file itself differs
    pinned["pool_summary_sha256"].write_text('{"changed": 1}')
    with pytest.raises(driver.ConfigPinError):
        driver.checked_config(config, expected, pinned)  # a pinned file changed


def test_the_served_model_must_be_the_pinned_gguf(monkeypatch):
    driver = stubbed_point(monkeypatch)
    config = {"model": "m", "gguf_size_bytes": 10, "gguf_n_params": 5}
    good = {"data": [{"id": "m", "meta": {"size": 10, "n_params": 5}}]}
    driver.checked_server(good, config)
    with pytest.raises(driver.ConfigPinError):
        driver.checked_server({"data": [{"id": "m", "meta": {"size": 11, "n_params": 5}}]}, config)


def test_steps_lost_counts_calls_from_the_error_to_the_next_success_of_the_program():
    from plug_agent2_branchpoint import steps_lost  # noqa: PLC0415

    point = find_branch_point(
        [TASK, ask("pytest t/a.py"), answer(FAIL)], known_for("pytest t/a.py")
    )
    assert point is not None
    start = list(point.messages)
    fixed = [
        *start,
        ask("pytest t/a.py"),
        answer(FAIL),
        ask("ls"),
        answer(PASS),
        ask("pytest t/a.py"),
        answer(PASS),
    ]
    assert steps_lost(fixed, point, window=15) == 2
    assert (
        steps_lost([*start, ask("ls"), answer(PASS)], point, window=15) == 0
    )  # the error never occurs


def test_a_replayed_command_must_return_the_recorded_code_and_error_line():
    from plug_agent2_branchpoint import matches_record  # noqa: PLC0415
    from plug_agent2_keys import executed_actions  # noqa: PLC0415

    step = executed_actions([TASK, ask("pytest t/a.py"), answer(FAIL)])[0]
    assert matches_record(step, {"returncode": 1, "output": "E   ValueError: bad\n"})
    assert not matches_record(step, {"returncode": 0, "output": "ok"})
    assert not matches_record(step, {"returncode": 1, "output": "E   KeyError: other\n"})


def test_the_co_primary_counts_any_failure_of_the_program_and_replacements_separately():
    from plug_agent2_branchpoint import program_failed_after, replacement_errors  # noqa: PLC0415

    point = find_branch_point(
        [TASK, ask("pytest t/a.py"), answer(FAIL)], known_for("pytest t/a.py")
    )
    assert point is not None
    other = "<returncode>1</returncode>\n<output>\nE   KeyError: other\n</output>"
    start = list(point.messages)
    swapped = [*start, ask("pytest t/b.py"), answer(other)]
    assert not repeated_after(swapped, point) and program_failed_after(swapped, point)
    assert replacement_errors(swapped, point) == 1
    clean = [*start, ask("pytest t/b.py"), answer(PASS)]
    assert not program_failed_after(clean, point) and replacement_errors(clean, point) == 0


def test_a_note_cannot_be_attached_to_a_message_without_text():
    point = find_branch_point(
        [{"role": "user", "content": None}, ask("pytest t/a.py"), answer(FAIL)],
        known_for("pytest t/a.py"),
    )
    assert point is not None
    with pytest.raises(TypeError):
        resume_messages(point, "NOTE")
