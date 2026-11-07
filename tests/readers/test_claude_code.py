import json
import os
import re
from pathlib import Path

import pytest

from symbiont.readers import READERS
from symbiont.readers.claude_code import read, read_open_swe_traces, read_swe_chat
from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind
from symbiont.records.session_tags import CREATED_TAG

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude_code"
SESSION = FIXTURES / "session.jsonl"
PROJECT = "acme/app"


@pytest.fixture(scope="module")
def records():
    return list(read(SESSION, PROJECT))


def of_kind(records, kind):
    return [r for r in records if r.kind == kind]


def test_registered_under_harness_names():
    assert READERS["claude-code"] is read
    assert READERS["swe-chat"] is read_swe_chat
    assert READERS["open-swe-traces-claudecode"] is read_open_swe_traces


def test_tool_use_bash_and_edit(records):
    (command,) = of_kind(records, Kind.COMMAND)
    assert command.command == "pytest tests/test_parser.py -q"
    assert command.exit_code == 1
    assert "FAILED tests/test_parser.py::test_a" in command.raw
    (edit,) = of_kind(records, Kind.EDIT)
    assert edit.files == ("src/parser.py",)
    assert "-return None\n+return []\n" in edit.diff
    assert edit.exit_code == 0
    assert edit.raw == "The file has been updated."


def test_read_and_other_tools_are_kept(records):
    (read_record,) = of_kind(records, Kind.READ)
    assert read_record.files == ("src/parser.py",)
    assert read_record.line_range == (10, 29)
    (other,) = of_kind(records, Kind.TOOL_RESULT)
    assert other.command == "Grep"
    assert other.exit_code is None


def test_turns_in_order_with_dense_steps_and_timestamps(records):
    assert [r.step for r in records] == list(range(len(records)))
    assert [r.kind for r in records] == [
        Kind.USER_TURN,
        Kind.AGENT_TURN,
        Kind.COMMAND,
        Kind.EDIT,
        Kind.READ,
        Kind.TOOL_RESULT,
        Kind.USER_TURN,
    ]
    assert records[0].ts == "2026-01-01T10:00:00Z"


def test_user_pushback_label_kept(records):
    first, last = of_kind(records, Kind.USER_TURN)
    assert first.tags == ("ai-title:Fix the failing parser test.",)
    assert last.kind == Kind.USER_TURN
    assert last.tags == ("correction",)
    assert last.raw.startswith("No, that is wrong")


def test_swe_chat_is_not_remote_safe():
    out = list(read_swe_chat(SESSION, PROJECT))
    assert {r.provenance.remote_safe for r in out} == {False}
    assert {r.provenance.dataset for r in out} == {"swe-chat"}


def test_open_swe_traces_claudecode_is_remote_safe():
    out = list(read_open_swe_traces(SESSION, PROJECT))
    assert {r.provenance.remote_safe for r in out} == {True}
    assert {r.provenance.dataset for r in out} == {"open-swe-traces"}


def test_user_private_sessions_not_remote_safe(records):
    assert {r.provenance.remote_safe for r in records} == {False}
    assert {r.provenance.dataset for r in records} == {"private-sessions"}


def test_symbiont_output_is_tagged_not_mined():
    out = list(read(FIXTURES / "with_our_output.jsonl", PROJECT))
    tagged, ours, plain = of_kind(out, Kind.COMMAND)[0], of_kind(out, Kind.TOOL_RESULT)[0], out[-1]
    assert tagged.tags == ()
    assert tagged.raw == "Exit code 1\n1 failed\n"
    assert tagged.exit_code == 1
    assert ours.tags == ("symbiont-output",)
    assert ours.raw.startswith("[symbiont]\nThis test failed the same way twice")
    assert plain.tags == () and plain.raw == "1 passed"


def test_recall_tool_result_is_ours_entirely():
    out = list(read(FIXTURES / "recall.jsonl", PROJECT))
    call, answer = out
    assert call.kind == Kind.TOOL_RESULT and call.raw == "" and call.tags == ()
    assert answer.tags == ("symbiont-output",)
    assert answer.raw == "This command failed twice in an earlier session."


def test_multi_edit_write_and_notebook_edit_are_edits():
    multi, write, notebook = list(read(FIXTURES / "edit_tools.jsonl", PROJECT))
    assert all(r.kind == Kind.EDIT for r in (multi, write, notebook))
    assert multi.files == ("a.py",)
    assert "-x = 1\n+x = 2\n" in multi.diff and "-y = 1\n+y = 2\n" in multi.diff
    assert write.files == ("new.py",)
    assert write.diff.startswith("--- /dev/null\n+++ b/new.py\n")
    assert "+print('hi')\n" in write.diff
    assert notebook.files == ("n.ipynb",)
    assert notebook.raw == "edited" and notebook.exit_code == 0


def test_metadata_events_are_skipped_and_counted(caplog):
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        out = list(read(FIXTURES / "metadata.jsonl", PROJECT))
    assert [r.kind for r in out] == [Kind.USER_TURN]
    assert out[0].step == 0
    assert "{'zz-bookmark': 2, 'zz-marker': 1}" in caplog.text


def test_unknown_type_with_a_message_raises_readerror():
    path = FIXTURES / "unknown_with_message.jsonl"
    with pytest.raises(ReadError, match="zz-note") as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 1 and err.value.path == path


def test_tool_result_content_object_raises_readerror():
    path = FIXTURES / "object_result.jsonl"
    with pytest.raises(ReadError, match="tool_result 'content'") as err:
        list(read(path, PROJECT))
    assert err.value.path == path


@pytest.mark.parametrize("kind", ["user", "assistant"])
def test_conversation_event_without_message_raises_readerror(tmp_path, kind):
    path = write_lines(tmp_path, [json.dumps({"type": kind, "sessionId": "s"})])
    with pytest.raises(ReadError, match=kind) as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 1


# --- lines the reader cannot parse are named, never skipped -----------------


def write_lines(tmp_path, lines):
    path = tmp_path / "session.jsonl"
    path.write_text("".join(line + "\n" for line in lines))
    return path


def fixture_lines():
    return SESSION.read_text(encoding="utf-8").splitlines()


def test_malformed_line_raises_readerror_with_line(tmp_path):
    good = fixture_lines()
    path = write_lines(tmp_path, [good[1], good[2][:60]])
    with pytest.raises(ReadError) as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 2
    assert err.value.path == path
    assert str(path) in str(err.value)


def test_unknown_event_type_raises_readerror(tmp_path):
    row = json.loads(fixture_lines()[1])
    row["type"] = "telepathy"
    with pytest.raises(ReadError, match="telepathy") as err:
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))
    assert err.value.line_no == 1


def test_missing_session_id_raises_readerror(tmp_path):
    row = json.loads(fixture_lines()[1])
    del row["sessionId"]
    with pytest.raises(ReadError, match="sessionId"):
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))


def test_tool_use_without_input_raises_readerror(tmp_path):
    row = json.loads(fixture_lines()[2])
    del row["message"]["content"][1]["input"]
    with pytest.raises(ReadError, match="input"):
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))


def _event(kind, content, **extra):
    return {"type": kind, "sessionId": "s", "message": {"role": kind, "content": content}, **extra}


def _tool(tool, tool_input, **overrides):
    block = {"type": "tool_use", "id": "t1", "name": tool, "input": tool_input, **overrides}
    return _event("assistant", [block])


def _result(**overrides):
    block = {"type": "tool_result", "tool_use_id": "t1", "content": "ok", **overrides}
    return _event("user", [block])


NOT_STRING_CASES = {
    "sessionId": ([{**_event("user", "hi"), "sessionId": 5}], "sessionId"),
    "type": ([{**_event("user", "hi"), "type": 5}], "'type' must be a string"),
    "timestamp": ([{**_event("user", "hi"), "timestamp": 5}], "timestamp"),
    "tool_result text block": (
        [_tool("Bash", {"command": "ls"}), _result(content=[{"type": "text", "text": 5}])],
        "text",
    ),
    "is_error": ([_tool("Bash", {"command": "ls"}), _result(is_error="yes")], "is_error"),
    "cwd": ([_event("user", "hi", cwd=5)], "cwd"),
    "user text": ([_event("user", [{"type": "text", "text": 5}])], "text"),
    "assistant text": ([_event("assistant", [{"type": "text", "text": 5}])], "text"),
    "tool_use id": ([_tool("Bash", {"command": "ls"}, id=5)], "id"),
    "tool_use_id": ([_result(tool_use_id=5)], "tool_use_id"),
    "tool name": ([_tool("Bash", {"command": "ls"}, name=5)], "name"),
}


@pytest.mark.parametrize("events, expected", NOT_STRING_CASES.values(), ids=NOT_STRING_CASES)
def test_non_string_field_raises_readerror_naming_file_and_line(tmp_path, events, expected):
    path = write_lines(
        tmp_path, [json.dumps(_event("user", "first"))] + [json.dumps(e) for e in events]
    )
    with pytest.raises(ReadError, match=expected) as err:
        list(read(path, PROJECT))
    assert err.value.path == path
    assert str(path) in str(err.value)
    assert err.value.line_no >= 2


def test_session_logs_are_found_by_the_repository_directory_oldest_first(tmp_path):
    from symbiont.readers.claude_code import session_logs

    repo = tmp_path / "work" / "my.repo"
    repo.mkdir(parents=True)
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    folder = tmp_path / "home" / ".claude" / "projects" / encoded
    folder.mkdir(parents=True)
    newer, older = folder / "b.jsonl", folder / "a.jsonl"
    newer.write_text("{}\n")
    older.write_text("{}\n")
    os.utime(older, (1, 1))
    (folder / "notes.txt").write_text("not a log")

    assert session_logs(repo, tmp_path / "home") == [older, newer]


def test_a_repository_with_no_session_folder_has_no_logs(tmp_path):
    from symbiont.readers.claude_code import session_logs

    assert session_logs(tmp_path, tmp_path / "home") == []


def piped_run(tmp_path, command, output):
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command}}
    result = {"type": "tool_result", "tool_use_id": "t1", "content": output}
    head = {"sessionId": "s", "timestamp": "2026-01-01T10:00:00Z", "cwd": "/w"}
    lines = [
        json.dumps(
            {"type": "assistant", **head, "message": {"role": "assistant", "content": [use]}}
        ),
        json.dumps({"type": "user", **head, "message": {"role": "user", "content": [result]}}),
    ]
    (command_record,) = of_kind(list(read(write_lines(tmp_path, lines), PROJECT)), Kind.COMMAND)
    return command_record


def test_a_failing_test_run_piped_through_head_is_a_failed_command(tmp_path):
    record = piped_run(tmp_path, "pytest -q 2>&1 | head -n 200", "F\n1 failed, 2 passed in 0.3s")
    assert record.exit_code == 1


def test_a_passing_test_run_piped_through_head_is_not_a_failure(tmp_path):
    record = piped_run(tmp_path, "pytest -q 2>&1 | head -n 200", "3 passed in 0.3s")
    assert record.exit_code == 0


# --- content the reader does not know is skipped, counted and logged ---------


def _read_events(tmp_path, *events):
    path = write_lines(tmp_path, [json.dumps(e) for e in events])
    return list(read(path, PROJECT))


def test_unknown_assistant_blocks_are_skipped_counted_and_logged(tmp_path, caplog):
    blocks = [
        {"type": "redacted_thinking", "data": "x"},
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}},
        {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
        {"type": "text", "text": "done"},
    ]
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        records = _read_events(tmp_path, _event("assistant", blocks))
    assert [r.raw for r in records] == ["done"]
    assert "unknown block type redacted_thinking" in caplog.text
    assert "unknown block type web_search_tool_result" in caplog.text


def test_edit_without_old_string_is_skipped_and_counted(tmp_path, caplog):
    edit = _tool("Edit", {"file_path": "a.py", "new_string": "x"})
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        records = _read_events(tmp_path, edit, _tool("Bash", {"command": "ls"}, id="t2"))
    assert [r.kind for r in records] == [Kind.COMMAND]
    assert "'Edit without old_string': 1" in caplog.text


@pytest.mark.parametrize("flag", ["isCompactSummary", "isMeta", "isSidechain"])
def test_harness_written_user_events_are_not_user_turns(tmp_path, caplog, flag):
    typed = _event("user", "no, use pytest")
    machine = _event("user", "Caveat: the messages below were generated", **{flag: True})
    with caplog.at_level("DEBUG", logger="symbiont.readers.claude_code"):
        records = _read_events(tmp_path, machine, typed)
    assert [r.raw for r in records] == ["no, use pytest"]
    assert "skipped" in caplog.text


def test_malformed_known_block_still_raises_after_tolerance(tmp_path):
    bad = _event("assistant", [{"type": "text", "text": 5}])
    with pytest.raises(ReadError, match="text"):
        _read_events(tmp_path, bad)


def test_the_plugin_named_recall_tool_result_is_ours_entirely(tmp_path):
    name = "mcp__plugin_symbiont_symbiont__recall"
    call = _tool(name, {"question": "why?"})
    answer = _result(content="This command failed twice in an earlier session.")
    call_rec, answer_rec = _read_events(tmp_path, call, answer)
    assert call_rec.raw == ""
    assert answer_rec.tags == ("symbiont-output",)
    assert answer_rec.raw.startswith("This command failed twice")


# --- request-log events carry a message but are not turns ---------------------


def test_api_request_blob_events_are_skipped_and_counted(tmp_path, caplog):
    turn = _event("user", "first")
    after = _event("user", "second")
    logged = [
        {"type": kind, "message": {"model": "m", "messages": []}}
        for kind in ("api-request-blob", "api-request", "api-request-shape")
    ]
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        with_blobs = _read_events(tmp_path, turn, *logged, after)
    without = _read_events(tmp_path, turn, after)
    assert [(r.kind, r.raw) for r in with_blobs] == [(r.kind, r.raw) for r in without]
    assert "'api-request-blob': 1" in caplog.text


def test_an_unknown_event_type_with_a_message_still_raises(tmp_path):
    path = write_lines(
        tmp_path, [json.dumps({"type": "api-request-new", "message": {"content": "x"}})]
    )
    with pytest.raises(ReadError, match="api-request-new") as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 1


# --- what the session was about: title and branch, kept as tags --------------


def test_the_ai_title_becomes_a_tag_on_the_sessions_first_user_turn(tmp_path):
    title = {"type": "ai-title", "aiTitle": "Fix tokenizer crash", "sessionId": "s"}
    records = _read_events(tmp_path, _event("user", "first"), title, _event("user", "second"))
    assert [r.tags for r in records] == [("ai-title:Fix tokenizer crash",), ()]


def test_the_git_branch_of_each_event_is_a_tag_on_its_records(tmp_path):
    records = _read_events(
        tmp_path,
        _event("user", "first", gitBranch="fix-window"),
        _event("assistant", [{"type": "text", "text": "ok"}], gitBranch="main"),
    )
    assert [r.tags for r in records] == [
        ("branch:fix-window", "ai-title:first"),
        ("branch:main",),
    ]


def test_an_event_without_a_branch_or_an_ai_title_is_titled_by_its_first_turn(tmp_path):
    (record,) = _read_events(tmp_path, _event("user", "first"))
    assert record.tags == ("ai-title:first",)


def slash_command(name="/clear"):
    return _event("user", f"<command-name>{name}</command-name>")


def test_a_slash_command_title_is_not_the_session_title(tmp_path):
    work = _event("user", "port the parser to rust\nthen the tests")
    first, _ = _read_events(tmp_path, slash_command(), work)
    assert first.tags == ("ai-title:port the parser to rust",)


def test_the_ai_title_beats_the_first_typed_turn(tmp_path):
    title = {"type": "ai-title", "aiTitle": "Port parser", "sessionId": "s"}
    first, _ = _read_events(tmp_path, slash_command(), title, _event("user", "go"))
    assert first.tags == ("ai-title:Port parser",)


def test_a_session_of_only_slash_commands_is_untitled(tmp_path):
    (record,) = _read_events(tmp_path, slash_command())
    assert record.tags == ("ai-title:untitled session",)


def test_routine_skips_are_logged_at_debug(tmp_path, caplog):
    meta = _event("user", "Caveat: generated", isMeta=True)
    note = _injected("task-notification")
    compact = _event("user", "summary", isCompactSummary=True)
    with caplog.at_level("DEBUG", logger="symbiont.readers.claude_code"):
        _read_events(tmp_path, meta, note, compact, _event("user", "go"))
    skipped = [r for r in caplog.records if "skipped" in r.getMessage()]
    assert {r.levelname for r in skipped} == {"DEBUG"}


def test_an_unusual_skip_is_logged_at_info_with_file_and_count(tmp_path, caplog):
    with caplog.at_level("DEBUG", logger="symbiont.readers.claude_code"):
        _read_events(tmp_path, _injected("scheduled"), _event("user", "go"))
    (skipped,) = [r for r in caplog.records if "skipped content" in r.getMessage()]
    assert skipped.levelname == "INFO"
    assert "session.jsonl" in skipped.getMessage() and "'scheduled': 1" in skipped.getMessage()


@pytest.mark.parametrize(
    "label, tags",
    [
        ("correction", ("correction",)),
        ("rejection", ("correction",)),
        (True, ("correction",)),
        ("failure_report", ("failure_report",)),
        ("non_pushback", ()),
        (False, ()),
        ("", ()),
        (None, ()),
    ],
)
def test_pushback_labels_map_to_tags(tmp_path, label, tags):
    turn = {**_event("user", "go"), "prompt_pushback": label}
    (record,) = _read_events(tmp_path, turn)
    assert tuple(t for t in record.tags if not t.startswith("ai-title:")) == tags


def test_an_unknown_pushback_label_raises_naming_it(tmp_path):
    turn = {**_event("user", "go"), "prompt_pushback": "surprise"}
    with pytest.raises(ReadError, match="surprise"):
        _read_events(tmp_path, turn)


def test_write_of_a_new_file_is_tagged_created_and_an_update_is_not(tmp_path):
    new = _tool("Write", {"file_path": "a.py", "content": "x\n"}, id="n")
    old = _tool("Write", {"file_path": "b.py", "content": "y\n"}, id="o")
    made = _result(tool_use_id="n", content="File created successfully at: /w/a.py")
    changed = _result(tool_use_id="o", content="The file /w/b.py has been updated successfully.")
    created, updated = _read_events(tmp_path, new, old, made, changed)
    assert CREATED_TAG in created.tags
    assert CREATED_TAG not in updated.tags


def test_a_title_that_is_not_text_raises_readerror(tmp_path):
    title = {"type": "ai-title", "aiTitle": 7, "sessionId": "s"}
    with pytest.raises(ReadError, match="aiTitle"):
        _read_events(tmp_path, _event("user", "first"), title)


def _injected(kind):
    return _event("user", "<task-notification>done</task-notification>", origin={"kind": kind})


def test_a_task_notification_is_not_a_user_turn_and_is_counted(tmp_path, caplog):
    typed = _event("user", "no, use pytest")
    with caplog.at_level("DEBUG", logger="symbiont.readers.claude_code"):
        records = _read_events(tmp_path, _injected("task-notification"), typed)
    assert [r.raw for r in records] == ["no, use pytest"]
    assert "'task notification': 1" in caplog.text


def test_a_message_from_another_session_is_not_a_user_turn(tmp_path, caplog):
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        records = _read_events(tmp_path, _injected("peer"), _injected("scheduled"))
    assert records == []
    assert "'message from another session': 1" in caplog.text
    assert "'scheduled': 1" in caplog.text


def test_a_human_origin_is_a_user_turn(tmp_path):
    typed = _event("user", "no, use pytest", origin={"kind": "human"})
    assert [r.raw for r in _read_events(tmp_path, typed)] == ["no, use pytest"]


def test_a_user_event_without_origin_is_still_a_user_turn(tmp_path):
    assert [r.raw for r in _read_events(tmp_path, _event("user", "hello"))] == ["hello"]


@pytest.mark.parametrize("origin", ["human", ["human"], {"kind": 3}, {}])
def test_a_malformed_origin_raises_naming_the_line(tmp_path, origin):
    path = write_lines(
        tmp_path,
        [json.dumps(_event("user", "ok")), json.dumps(_event("user", "x", origin=origin))],
    )
    with pytest.raises(ReadError, match=r":2\b|line 2"):
        list(read(path, PROJECT))


@pytest.mark.parametrize(
    "markup",
    [
        "<command-message>clear</command-message><command-name>/clear</command-name>",
        "<command-message>init</command-message>\n<command-name>/init</command-name>",
        "<local-command-stdout>Set model to X</local-command-stdout>",
        "/compact now",
    ],
)
def test_command_markup_and_command_output_never_title_a_session(tmp_path, markup):
    first, _ = _read_events(tmp_path, _event("user", markup), _event("user", "fix the lexer"))
    assert first.tags == ("ai-title:fix the lexer",)


def test_a_typed_path_is_a_title_not_a_slash_command(tmp_path):
    (record,) = _read_events(tmp_path, _event("user", "/tmp/build/out.log has the crash"))
    assert record.tags == ("ai-title:/tmp/build/out.log has the crash",)


def test_the_title_pass_does_not_raise_pushback_errors_twice(tmp_path):
    bad = {**_event("user", "go"), "prompt_pushback": "surprise"}
    with pytest.raises(ReadError, match="surprise") as err:
        _read_events(tmp_path, bad)
    assert err.value.line_no == 1


UNPARSED = {"_swe_chat_unparsed": "raw text the exporter could not parse"}


def test_swe_chat_skips_and_counts_a_line_the_dataset_could_not_parse(tmp_path, caplog):
    path = write_lines(tmp_path, [json.dumps(_event("user", "go")), json.dumps(UNPARSED)])
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        records = list(read_swe_chat(path, PROJECT))
    assert [r.raw for r in records] == ["go"]
    infos = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any(
        "line the dataset could not parse" in m and "1" in m and "session.jsonl" in m for m in infos
    )


def test_claude_code_own_logs_still_raise_for_a_line_without_type(tmp_path):
    path = write_lines(tmp_path, [json.dumps(UNPARSED)])
    with pytest.raises(ReadError, match="type"):
        list(read(path, PROJECT))
    with pytest.raises(ReadError, match="type"):
        list(read_open_swe_traces(path, PROJECT))


def test_swe_chat_skips_and_counts_a_json_line_that_is_not_an_object(tmp_path, caplog):
    path = write_lines(tmp_path, [json.dumps(_event("user", "go")), json.dumps([1, 2])])
    with caplog.at_level("INFO", logger="symbiont.readers.claude_code"):
        records = list(read_swe_chat(path, PROJECT))
    assert [r.raw for r in records] == ["go"]
    infos = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any("line the dataset could not parse': 1" in m and "session.jsonl" in m for m in infos)


def test_claude_code_own_logs_still_raise_for_a_line_that_is_not_an_object(tmp_path):
    path = write_lines(tmp_path, [json.dumps([1, 2])])
    for reader in (read, read_open_swe_traces):
        with pytest.raises(ReadError, match="event object"):
            list(reader(path, PROJECT))
