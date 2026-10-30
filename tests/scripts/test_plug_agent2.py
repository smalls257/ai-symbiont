"""PLUG-AGENT-2: the frozen known-mistake key, the repeat reading and the label reply check."""

import json
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_errorline import is_generic_environment, normalize_error_line  # noqa: E402
from plug_agent2_keys import failures_in, key_of, read_run  # noqa: E402
from plug_agent2_label import LabelReplyError, parsed_labels  # noqa: E402
from plug_agent_notes import Failure  # noqa: E402


def failure(error: str, program: str = "pytest", target: str = "t/a.py") -> Failure:
    return Failure(f"{program} {target}", error, program, target)


def test_key_is_the_normalized_error_line_and_masks_volatile_parts():
    first = key_of(failure("ValueError: bad file /tmp/abc/x.py line 12 at 0xdeadbeef"))
    second = key_of(failure("ValueError: bad file /home/u/y.py line 98 at 0xcafe1234"))
    assert first == second and first is not None
    assert key_of(failure("ValueError: other")) != first


def test_an_empty_or_placeholder_only_line_gives_no_key():
    assert key_of(failure("")) is None
    assert key_of(failure("/tmp/x/y 12345")) is None


def test_generic_environment_errors_are_split_from_code_specific_ones():
    assert is_generic_environment(normalize_error_line("ModuleNotFoundError: No module named 'x'"))
    assert is_generic_environment(normalize_error_line("bash: pip: command not found"))
    assert not is_generic_environment(normalize_error_line("KeyError: 'application/json'"))
    assert not is_generic_environment(
        normalize_error_line("AttributeError: 'A' has no attribute 'b'")
    )


def test_repeat_is_counted_only_for_the_first_known_key():
    a, b = failure("ValueError: x"), failure("KeyError: y")
    known = frozenset({key_of(a)})
    reading = read_run([b, a, None, b, a], known)
    assert (reading.first_known, reading.repeated, reading.any_key_repeats) == (1, True, 2)
    assert read_run([a, b], known).repeated is False
    assert read_run([b, b], known).first_known is None


def test_keyless_failures_are_counted_apart():
    reading = read_run([failure(""), failure("")], frozenset())
    assert (reading.failures, reading.keyless) == (2, 2)


def test_failures_follow_the_tool_call_order():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"arguments": json.dumps({"command": "pytest t/a.py"})}}],
        },
        {
            "role": "tool",
            "content": "<returncode>1</returncode>\n<output>\nE   ValueError: bad\n</output>",
        },
        {
            "role": "assistant",
            "tool_calls": [{"function": {"arguments": json.dumps({"command": "ls"})}}],
        },
        {"role": "tool", "content": "<returncode>0</returncode>\n<output>\n</output>"},
    ]
    found = failures_in(messages)
    assert found[1] is None and found[0] is not None


def test_label_reply_must_be_exact():
    assert parsed_labels('{"labels": ["applies", "does_not_apply"]}', 2) == [
        "applies",
        "does_not_apply",
    ]
    for bad in ('{"labels": ["applies"]}', "yes", '{"labels": ["maybe", "applies"]}'):
        with pytest.raises(LabelReplyError):
            parsed_labels(bad, 2)


def test_normalizer_is_stable_and_masks_the_volatile_parts():
    path = "/tmp/pytest-of-root/pytest-7/x.py"
    line = f"FileNotFoundError: [Errno 2] No such file: '{path}' at 2026-10-29 10:00:01"
    once = normalize_error_line(line)
    assert normalize_error_line(once) == once
    assert "pytest-7" not in once and "2026" not in once
    assert normalize_error_line("KeyError: 'application/json'") == "KeyError: '<path>'"


def test_points_in_the_same_task_but_different_runs_have_different_ids():
    from plug_agent2_points import points_of_run  # noqa: PLC0415

    lesson = {"lesson_id": "L1", "failed": "pytest t/a.py", "error": "ValueError: bad"}
    messages = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "extra": {"actions": [{"command": "pytest t/a.py"}]}},
        {
            "role": "tool",
            "content": "<returncode>1</returncode>\n<output>\nE   ValueError: bad\n</output>",
        },
    ]
    first = points_of_run("t-1", "a/run.traj.json", messages, {"L1": "applies"}, [lesson])
    second = points_of_run("t-1", "b/run.traj.json", messages, {"L1": "applies"}, [lesson])
    assert first[0]["id"] != second[0]["id"] and first[0]["lessons"] == ["L1"]
