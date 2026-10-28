import json
from pathlib import Path

import pytest

from symbiont.readers import READERS
from symbiont.readers.claude_code import read, read_open_swe_traces, read_swe_chat
from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind

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
    assert first.tags == ()
    assert last.kind == Kind.USER_TURN
    assert last.tags == ("correction",)
    assert last.raw.startswith("No, that is wrong")


def test_swe_chat_is_not_spark_safe():
    out = list(read_swe_chat(SESSION, PROJECT))
    assert {r.provenance.spark_safe for r in out} == {False}
    assert {r.provenance.dataset for r in out} == {"swe-chat"}


def test_open_swe_traces_claudecode_is_spark_safe():
    out = list(read_open_swe_traces(SESSION, PROJECT))
    assert {r.provenance.spark_safe for r in out} == {True}
    assert {r.provenance.dataset for r in out} == {"open-swe-traces"}


def test_user_private_sessions_not_spark_safe(records):
    assert {r.provenance.spark_safe for r in records} == {False}
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
    return SESSION.read_text().splitlines()


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
