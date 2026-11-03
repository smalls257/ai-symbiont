"""Muse Code session logs: hand-written lines in the shape its read-session skill documents.

Failure guarded against: a reader that skips what it cannot parse and trains on less.
"""

import json
import os

import pytest

from symbiont.readers import READERS
from symbiont.readers.errors import ReadError
from symbiont.readers.muse_code import read, same_workspace_key, session_logs
from symbiont.records.schema import Kind

SESSION = "01a00000-0000-7000-8000-000000000001"


def line(payload_type, payload, session=SESSION):
    return json.dumps(
        {
            "schema_version": 1,
            "stream": {"kind": "session", "id": session},
            "recorded_at": 1793638784408642,
            "payload_type": payload_type,
            "payload": payload,
        }
    )


def run_event(event, kind="run"):
    return line("runtime.session", {"kind": kind, "run_id": "r1", "event": event})


def metadata(root):
    return line(
        "runtime.session.metadata", {"kind": "metadata", "record": {"workspace_root": root}}
    )


def write(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def calls(*tool_calls):
    return run_event({"kind": "assistant_tool_calls_committed", "tool_calls": list(tool_calls)})


def results(*batch):
    return run_event({"kind": "tool_result_batch_committed", "results": list(batch)})


def test_prompts_and_answers_become_turns_and_other_lines_are_not_conversation(tmp_path):
    log = write(
        tmp_path / "session.jsonl",
        json.dumps({"retained_frame": "session_permission_transaction", "children": []}),
        metadata("/work/demo"),
        run_event({"kind": "started", "prompt": "fix the build"}),
        run_event({"kind": "started", "task_id": "t1"}, kind="task"),
        run_event({"kind": "model_completed"}),
        run_event({"kind": "assistant_message_committed", "text": "on it"}),
    )

    records = list(read(log, "demo"))

    assert [(r.kind, r.raw) for r in records] == [
        (Kind.USER_TURN, "fix the build"),
        (Kind.AGENT_TURN, "on it"),
    ]
    assert [r.step for r in records] == [0, 1]
    assert records[0].harness == "muse-code" and records[0].project == "demo"
    assert not records[0].provenance.spark_safe, "unknown privacy is never shareable"


def test_a_shell_call_carries_its_command_output_and_exit_status(tmp_path):
    log = write(
        tmp_path / "session.jsonl",
        calls({"name": "bash", "call_id": "c1", "args": {"cmd": "pytest -q"}}),
        results({"call_id": "c1", "text": "ImportError: no module", "exit_code": 2}),
    )

    (record,) = read(log, "demo")

    assert (record.kind, record.command, record.exit_code) == (Kind.COMMAND, "pytest -q", 2)
    assert record.raw == "ImportError: no module"


def test_muses_windows_powershell_tool_is_a_command(tmp_path):
    log = write(
        tmp_path / "session.jsonl",
        calls({"name": "powershell", "call_id": "c1", "args": '{"command": "dir"}'}),
        results({"call_id": "c1", "text": "gone", "exit_code": 1}),
    )

    (record,) = read(log, "demo")

    assert (record.kind, record.command, record.exit_code) == (Kind.COMMAND, "dir", 1)


def test_a_shell_result_with_no_reported_status_is_unknown_not_success(tmp_path):
    log = write(
        tmp_path / "session.jsonl",
        calls({"name": "bash", "call_id": "c1", "args": '{"command": "ls"}'}),
        results({"call_id": "c1", "text": "a b"}),
    )

    (record,) = read(log, "demo")

    assert record.command == "ls" and record.exit_code is None


def test_edits_and_reads_name_their_files_and_other_tools_keep_their_result(tmp_path):
    log = write(
        tmp_path / "session.jsonl",
        calls(
            {"name": "edit_file", "call_id": "e", "args": {"path": "app/a.py", "patch": "+x"}},
            {"name": "read_file", "call_id": "r", "args": {"path": "app/b.py"}},
            {"name": "mcp__plugin_symbiont_symbiont__recall", "call_id": "m", "args": {}},
        ),
        results({"call_id": "m", "text": "a note"}),
    )

    edit, viewed, other = read(log, "demo")

    assert (edit.kind, edit.files, edit.diff) == (Kind.EDIT, ("app/a.py",), "+x")
    assert (viewed.kind, viewed.files) == (Kind.READ, ("app/b.py",))
    assert (other.kind, other.raw) == (Kind.TOOL_RESULT, "a note")


def test_a_line_that_is_not_json_raises_naming_file_and_line(tmp_path):
    log = write(tmp_path / "session.jsonl", metadata("/w"), "{not json")

    with pytest.raises(ReadError, match=r"session\.jsonl:2: not valid JSON"):
        list(read(log, "demo"))


def test_a_conversation_event_missing_its_field_raises_naming_the_line(tmp_path):
    log = write(tmp_path / "session.jsonl", run_event({"kind": "started"}))

    with pytest.raises(ReadError, match=r":1: 'prompt' must be a string"):
        list(read(log, "demo"))


def test_a_tool_result_with_no_call_id_raises(tmp_path):
    log = write(tmp_path / "session.jsonl", results({"text": "orphan"}))

    with pytest.raises(ReadError, match="no call id"):
        list(read(log, "demo"))


def test_the_reader_is_registered_by_harness_name():
    assert READERS["muse-code"] is read


def sessions_root(home):
    return home / "muse" / "sessions" / "2026" / "11" / "02"


def test_session_logs_are_found_by_workspace_oldest_first_without_subagents(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    home = tmp_path / "data"
    newer = write(sessions_root(home) / "b" / "session.jsonl", metadata(str(repo.resolve())))
    older = write(sessions_root(home) / "a" / "session.jsonl", metadata(str(repo.resolve())))
    write(sessions_root(home) / "c" / "session.jsonl", metadata(str(other.resolve())))
    write(
        sessions_root(home) / "d" / "session.jsonl", run_event({"kind": "started", "prompt": "x"})
    )
    write(sessions_root(home) / "a" / "subagent" / "z" / "session.jsonl", metadata(str(repo)))
    os.utime(older, (1, 1))

    assert session_logs(repo, home) == [older, newer]


def test_a_broken_log_in_the_store_raises_instead_of_being_skipped(tmp_path):
    home = tmp_path / "data"
    write(sessions_root(home) / "a" / "session.jsonl", "{broken")

    with pytest.raises(ReadError, match="session.jsonl:1"):
        session_logs(tmp_path, home)


def test_the_shape_muse_code_really_writes_for_shell_and_edit_calls(tmp_path):
    report = {"command": "pytest -q t.py", "exit_code": 1, "output": "E assert 1 == 2\n"}
    log = write(
        tmp_path / "session.jsonl",
        run_event({"kind": "started", "task_id": "t1"}, kind="task"),
        calls(
            {
                "id": "fc_1",
                "call_id": "call_1",
                "name": "bash",
                "args": json.dumps({"command": "pytest -q t.py", "description": "run"}),
            },
            {
                "id": "fc_2",
                "call_id": "call_2",
                "name": "edit_file",
                "args": json.dumps({"path": "t.py", "find": "1 == 2", "replace": "1 == 1"}),
            },
        ),
        results(
            {"tool_call_index": 0, "tool_call_id": "call_1", "text": json.dumps(report)},
            {"tool_call_index": 1, "tool_call_id": "call_2", "text": "edited\n"},
        ),
    )

    shell, edit = read(log, "demo")

    assert (shell.command, shell.exit_code, shell.raw) == ("pytest -q t.py", 1, report["output"])
    assert (edit.files, edit.diff) == (("t.py",), "-1 == 2\n+1 == 1\n")


def piped_record(tmp_path, output):
    log = write(
        tmp_path / "session.jsonl",
        calls({"name": "bash", "call_id": "c1", "args": {"cmd": "pytest -q 2>&1 | head -n 200"}}),
        results({"call_id": "c1", "text": output, "exit_code": 0}),
    )
    (record,) = read(log, "demo")
    return record


def test_a_failing_test_run_piped_through_head_is_a_failed_command_though_muse_said_0(tmp_path):
    assert piped_record(tmp_path, "F\n1 failed, 2 passed in 0.3s").exit_code == 1


def test_a_passing_test_run_piped_through_head_stays_a_success(tmp_path):
    assert piped_record(tmp_path, "3 passed in 0.3s").exit_code == 0


@pytest.mark.parametrize(
    "recorded",
    [
        "\\\\?\\C:\\Users\\small\\AppData\\Local\\Temp\\musetest",
        "c:/users/small/appdata/local/temp/musetest/",
        "C:\\Users\\small\\AppData\\Local\\Temp\\musetest\\",
    ],
)
def test_windows_spellings_of_one_workspace_share_a_key(recorded):
    shown = "C:\\Users\\small\\AppData\\Local\\Temp\\musetest"
    assert same_workspace_key(recorded) == same_workspace_key(shown)


def test_unc_prefix_and_posix_case_rules():
    assert same_workspace_key("\\\\?\\UNC\\Srv\\Share\\x") == same_workspace_key(
        "\\\\srv\\share\\X"
    )
    assert same_workspace_key("/home/Me/repo") != same_workspace_key("/home/me/repo")
    assert same_workspace_key("D:\\a") != same_workspace_key("C:\\a")


def test_a_session_recorded_with_the_extended_length_prefix_is_found(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "data"
    log = write(
        sessions_root(home) / "a" / "session.jsonl", metadata("\\\\?\\" + str(repo.resolve()))
    )
    assert session_logs(repo, home) == [log]
