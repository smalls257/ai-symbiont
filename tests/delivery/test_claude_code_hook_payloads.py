"""Claude Code's hook payloads, shaped as its hook docs describe them (synthetic text).

A Claude Code success carried no exit code and was stored
as unknown; a user interrupt arrived as a failure and was stored as a failed command.
"""

import pytest

from symbiont.delivery import hooks
from symbiont.delivery.hooks import HookEvent

pytestmark = pytest.mark.periphery

OUTPUT = "F\nE  AssertionError\n1 failed in 0.02s\n"


def payload(event: HookEvent, tool: str, tool_input: dict, **fields) -> dict:
    return {
        "session_id": "abc-synthetic",
        "transcript_path": "/tmp/synthetic/abc.jsonl",
        "cwd": "/tmp/synthetic/proj",
        "hook_event_name": event.value,
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_synthetic",
        **fields,
    }


def record_of(data: dict) -> dict:
    event = HookEvent(data["hook_event_name"])
    return hooks.observe_body(event, data, "claude_code", "p")["payload"]["record"]


def test_a_successful_bash_call_records_exit_code_zero():
    done = payload(
        HookEvent.POST_TOOL_USE,
        "Bash",
        {"command": "ls"},
        tool_response={"stdout": "a\nb\n", "stderr": "", "interrupted": False, "isImage": False},
    )
    record = record_of(done)
    assert (record["kind"], record["command"], record["exit_code"]) == ("command", "ls", 0)
    assert record["raw"] == "a\nb\n"


def test_a_failed_bash_call_keeps_the_exit_code_its_error_text_names():
    failed = payload(
        HookEvent.POST_TOOL_USE_FAILURE,
        "Bash",
        {"command": "pytest"},
        error="Exit code 2\n" + OUTPUT,
        is_interrupt=False,
    )
    record = record_of(failed)
    assert record["exit_code"] == 2
    assert "AssertionError" in record["raw"]


def test_a_failure_without_an_exit_code_line_is_one():
    failed = payload(HookEvent.POST_TOOL_USE_FAILURE, "Bash", {"command": "x"}, error="boom")
    assert record_of(failed)["exit_code"] == 1


def test_an_interrupted_call_is_not_a_command_failure():
    stopped = payload(
        HookEvent.POST_TOOL_USE_FAILURE,
        "Bash",
        {"command": "sleep 100"},
        error="Command was aborted before completion",
        is_interrupt=True,
    )
    assert record_of(stopped)["exit_code"] is None


def test_stdout_that_starts_with_exit_code_is_not_read_as_a_status():
    done = payload(
        HookEvent.POST_TOOL_USE,
        "Bash",
        {"command": "echo"},
        tool_response={"stdout": "Exit code 7 is documented", "stderr": "", "interrupted": False},
    )
    assert record_of(done)["exit_code"] == 0


def test_non_shell_tools_are_unchanged():
    edit = payload(
        HookEvent.POST_TOOL_USE,
        "Edit",
        {"file_path": "/tmp/synthetic/proj/a.py", "old_string": "a", "new_string": "b"},
        tool_response={"filePath": "a.py", "success": True},
    )
    assert record_of(edit)["kind"] == "edit"
