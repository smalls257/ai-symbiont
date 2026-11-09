"""A tool call the tool itself would reject is the agent's mistake, not a bad history file."""

import json
import logging

import pytest

from symbiont.miner.changes import applied_edit
from symbiont.readers.claude_code import read
from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind

PROJECT = "acme/app"
LOGGER = "symbiont.readers.claude_code"


def event(kind, content, **extra):
    return {"type": kind, "sessionId": "s", "message": {"role": kind, "content": content}, **extra}


def tool(name, tool_input, call_id="t1"):
    block = {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}
    return event("assistant", [block])


def failure(call_id="t1", text="InputValidationError: bad input"):
    block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": True}
    return event("user", [block])


def read_events(tmp_path, *events):
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return list(read(path, PROJECT))


@pytest.mark.parametrize(
    "name, tool_input, kind",
    [
        ("Read", {"file_path": "a.py", "offset": "25"}, Kind.READ),
        ("Read", {"file_path": "a.py", "offset": 1, "limit": "1, "}, Kind.READ),
        ("Read", {"offset": 3}, Kind.READ),
        ("Read", {"file_path": 5}, Kind.READ),
        ("Bash", {"description": "list"}, Kind.COMMAND),
        ("Bash", {"command": 5}, Kind.COMMAND),
        ("Edit", {"old_string": "a", "new_string": "b"}, Kind.EDIT),
        ("Edit", {"file_path": "a.py", "old_string": "a", "new_string": 5}, Kind.EDIT),
        ("Write", {"content": "x"}, Kind.EDIT),
        ("Write", {"file_path": "a.py"}, Kind.EDIT),
        ("MultiEdit", {"file_path": "a.py", "edits": "no"}, Kind.EDIT),
        ("NotebookEdit", {"new_source": "x"}, Kind.EDIT),
    ],
)
def test_a_call_the_tool_rejects_is_a_refused_action_and_later_rows_read(
    tmp_path, name, tool_input, kind
):
    records = read_events(tmp_path, tool(name, tool_input), failure(), event("user", "next"))
    refused, after = records
    assert refused.kind == kind
    assert refused.exit_code == 1
    assert refused.diff is None
    assert refused.raw == "InputValidationError: bad input"
    assert after.kind == Kind.USER_TURN


def test_a_refused_read_keeps_its_file_and_a_refused_edit_is_no_applied_edit(tmp_path):
    read_call = tool("Read", {"file_path": "a.py", "offset": "25"})
    edit_call = tool("Write", {"file_path": "b.py"}, call_id="t2")
    first, second = read_events(tmp_path, read_call, edit_call)
    assert first.files == ("a.py",)
    assert second.files == ("b.py",)
    assert not applied_edit(second)


def test_a_refused_call_without_a_result_keeps_the_reason(tmp_path):
    (record,) = read_events(tmp_path, tool("Bash", {}))
    assert record.exit_code == 1
    assert "command" in record.raw


def test_one_warning_per_file_counts_the_refused_calls(tmp_path, caplog):
    calls = [tool("Read", {"file_path": "a", "offset": "1"}, call_id=f"t{i}") for i in range(3)]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        read_events(tmp_path, *calls)
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage().endswith("kept 3 malformed tool calls as refused actions")
    assert "session.jsonl" in warning.getMessage()


def test_a_file_without_refused_calls_logs_no_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        read_events(tmp_path, tool("Bash", {"command": "ls"}))
    assert caplog.records == []


@pytest.mark.parametrize(
    "line", ["[1, 2]", '{"sessionId": "s", "message": {"content": "hi"}}', '{"type": 5}']
)
def test_structural_problems_still_raise_readerror(tmp_path, line):
    path = tmp_path / "session.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ReadError):
        list(read(path, PROJECT))


def test_a_tool_input_that_is_not_an_object_still_raises_readerror(tmp_path):
    with pytest.raises(ReadError, match="object"):
        read_events(tmp_path, tool("Read", "a.py"))


def test_every_refused_action_carries_the_refused_tag(tmp_path):
    records = read_events(
        tmp_path, tool("Bash", {}), tool("Read", {"file_path": "a", "offset": "1"}, "t2")
    )
    assert [r.tags for r in records] == [("refused",), ("refused",)]
