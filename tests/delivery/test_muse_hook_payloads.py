"""Muse Code's hook payloads, shaped as `muse exec` sent them (synthetic text, real field layout).

Violation prevented: Silent Fallback. Muse sends a shell result as a string holding a JSON object,
in `tool_response` and (for failures) `error`. Read as plain text, its exit code vanished: a
failed command that arrived as PostToolUse looked like a pass and was dropped without a trace.
"""

import json

import pytest

from symbiont.delivery import hooks
from symbiont.delivery.hooks import HookEvent

pytestmark = pytest.mark.periphery

OUTPUT = "F\n_ test_a _\n>  assert 1 == 2\nE  AssertionError\n1 failed in 0.02s\n"


def muse_shell_result(exit_code: int, output: str) -> str:
    status = "completed" if exit_code == 0 else "failed"
    envelope = {"chunk_id": "exec-1-1", "exit_code": exit_code, "terminal_status": status}
    return json.dumps(envelope | {"output": output, "truncated": False}, indent=2)


def muse_payload(event: HookEvent, tool: str, arguments: dict, result: str) -> dict:
    field = "error" if event is HookEvent.POST_TOOL_USE_FAILURE else "tool_response"
    return {
        "hook_event_name": event.value,
        "tool_name": tool,
        "tool_input": arguments,
        "tool_use_id": "call_synthetic",
        field: result,
        "session_id": "01a1-synthetic",
        "cwd": "/private/tmp/ws",
        "model_provider": "meta",
    }


def record_of(payload: dict) -> dict:
    event = HookEvent(payload["hook_event_name"])
    return hooks.observe_body(event, payload, "muse_code", "p")["payload"]["record"]


def test_a_muse_failure_keeps_its_real_exit_code_and_readable_output():
    failure = muse_payload(
        HookEvent.POST_TOOL_USE_FAILURE, "bash", {"command": "pytest"}, muse_shell_result(3, OUTPUT)
    )
    record = record_of(failure)
    assert (record["kind"], record["command"], record["exit_code"]) == ("command", "pytest", 3)
    assert record["raw"] == OUTPUT


def test_a_muse_post_tool_use_with_a_nonzero_exit_is_a_failed_command():
    done = muse_payload(
        HookEvent.POST_TOOL_USE, "bash", {"command": "pytest"}, muse_shell_result(1, OUTPUT)
    )
    assert record_of(done)["exit_code"] == 1


def test_a_muse_pass_reads_as_exit_zero():
    done = muse_payload(
        HookEvent.POST_TOOL_USE, "bash", {"command": "ls"}, muse_shell_result(0, "a\n")
    )
    assert record_of(done)["exit_code"] == 0


def test_muse_exec_command_is_a_shell_tool():
    done = muse_payload(
        HookEvent.POST_TOOL_USE, "exec_command", {"command": "ls"}, muse_shell_result(2, "x")
    )
    assert (record_of(done)["kind"], record_of(done)["exit_code"]) == ("command", 2)


def test_muse_file_tools_are_read_and_edit_records():
    read = muse_payload(HookEvent.POST_TOOL_USE, "read_file", {"path": "a.py"}, "1|x")
    edit = muse_payload(HookEvent.POST_TOOL_USE, "edit_file", {"path": "a.py"}, "ok")
    assert [record_of(read)["kind"], record_of(edit)["kind"]] == ["read", "edit"]
    assert record_of(read)["files"] == ["a.py"]


def test_a_plain_text_error_from_claude_code_stays_text_with_failure_code_one():
    failure = {
        "session_id": "s",
        "tool_name": "Bash",
        "tool_input": {"command": "false"},
        "error": "Exit code 1",
    }
    record = record_of(failure | {"hook_event_name": "PostToolUseFailure"})
    assert (record["raw"], record["exit_code"]) == ("Exit code 1", 1)
