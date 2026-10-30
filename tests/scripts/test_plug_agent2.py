"""PLUG-AGENT-2: the frozen known-mistake key, the repeat reading and the label reply check."""

import json
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_keys import failures_in, key_of, read_run  # noqa: E402
from plug_agent2_label import LabelReplyError, parsed_labels  # noqa: E402
from plug_agent_notes import Failure  # noqa: E402


def failure(error: str, program: str, target: str) -> Failure:
    return Failure(f"{program} {target}", error, program, target)


def test_generic_key_without_a_file_target_gives_no_key():
    assert key_of(failure("ModuleNotFoundError: x", "python", "-")) is None
    assert key_of(failure("ModuleNotFoundError: x", "-", "a.py")) is None
    assert key_of(failure("no class here", "python", "a.py")) is None


def test_specific_key_has_class_program_and_file():
    assert key_of(failure("ValueError: bad", "pytest", "tests/a.py")) == (
        "ValueError",
        "pytest",
        "tests/a.py",
    )


def test_repeat_is_counted_only_for_the_first_known_key():
    a, b = failure("ValueError: x", "pytest", "t/a.py"), failure("KeyError: y", "python", "b.py")
    known = frozenset({key_of(a)})
    reading = read_run([b, a, None, b, a], known)
    assert (reading.first_known, reading.repeated, reading.any_key_repeats) == (1, True, 2)
    assert read_run([a, b], known).repeated is False
    assert read_run([b, b], known).first_known is None


def test_keyless_failures_are_counted_apart():
    generic = failure("OSError: z", "python", "-")
    reading = read_run([generic, generic], frozenset())
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
