import json
from pathlib import Path

import pytest

from symbiont.readers import READERS
from symbiont.readers.errors import ReadError
from symbiont.readers.mini_swe_agent import read, read_local_run, read_open_swe_traces
from symbiont.records.schema import Kind

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_swe_agent"
RUNS = FIXTURES / "two_runs.jsonl"
PROJECT = "tobymao/sqlglot"


@pytest.fixture(scope="module")
def records():
    return list(read_open_swe_traces(RUNS, PROJECT))


def session(records, session_id):
    return [r for r in records if r.session_id == session_id]


def of_kind(records, kind):
    return [r for r in records if r.kind == kind]


def test_registered_under_entry_point_names():
    assert READERS["mini-swe-agent"] is read
    assert READERS["open-swe-traces-minisweagent"] is read_open_swe_traces
    assert READERS["local-run"] is read_local_run


def test_bash_block_becomes_command(records):
    commands = of_kind(session(records, "mswe-sqlglot-1"), Kind.COMMAND)
    grep, tests, submit = commands
    assert grep.command == "grep -n ARRAY_SORT /testbed/sqlglot/dialects/duckdb.py"
    assert grep.exit_code == 0
    assert tests.command == "python -m pytest tests/dialects/test_duckdb.py -x -q"
    assert tests.exit_code == 1
    assert "ImportError: cannot import name 'SortArray'" in tests.raw
    assert submit.exit_code is None
    assert submit.raw == ""


def test_thought_becomes_agent_turn(records):
    first = session(records, "mswe-sqlglot-1")
    assert first[0].kind == Kind.USER_TURN
    assert first[1].kind == Kind.AGENT_TURN
    assert first[1].raw == "THOUGHT: Find the dialect file."
    assert [r.step for r in first] == list(range(len(first)))


def test_sed_or_heredoc_write_becomes_edit(records):
    sed, heredoc = of_kind(session(records, "mswe-sqlglot-1"), Kind.EDIT)
    assert sed.files == ("sqlglot/dialects/duckdb.py",)
    assert sed.command.startswith("sed -i ")
    assert heredoc.files == ("reproduce.py",)


def test_heredoc_body_is_not_scanned_for_files(records):
    heredoc = of_kind(session(records, "mswe-sqlglot-1"), Kind.EDIT)[1]
    assert heredoc.files == ("reproduce.py",)


def test_chained_sed_with_backup_suffix_and_dev_null(records):
    (edit,) = of_kind(session(records, "glimmer-run-7"), Kind.EDIT)
    assert edit.files == ("django/contrib/admin/filters.py",)


def test_read_only_command_has_no_files(records):
    ls = of_kind(session(records, "glimmer-run-7"), Kind.COMMAND)[0]
    assert ls.files == ()


def test_open_swe_traces_provenance(records):
    (provenance,) = {r.provenance for r in records}
    assert provenance.dataset == "open-swe-traces"
    assert provenance.spark_safe is True


def test_own_run_provenance():
    out = list(read_local_run(RUNS, PROJECT))
    (provenance,) = {r.provenance for r in out}
    assert provenance.dataset == "local-run"
    assert provenance.spark_safe is True


def test_default_read_is_never_spark_safe():
    out = list(read(RUNS, PROJECT))
    assert {r.provenance.spark_safe for r in out} == {False}


def test_local_run_refuses_a_task_that_is_not_a_public_benchmark_id(tmp_path):
    row = fixture_rows()[0]
    row["instance_id"] = "my-private-task"
    with pytest.raises(ReadError, match="my-private-task"):
        list(read_local_run(write_lines(tmp_path, [json.dumps(row)]), PROJECT))


def test_task_id_is_instance_id(records):
    assert {r.session_id: r.task_id for r in records} == {
        "mswe-sqlglot-1": "tobymao__sqlglot-4001",
        "glimmer-run-7": "django__django-15000",
    }


def test_symbiont_output_is_tagged_not_mined():
    out = list(read_open_swe_traces(FIXTURES / "with_our_output.jsonl", PROJECT))
    first, ours = out[2], out[3]
    assert first.kind == Kind.COMMAND
    assert first.tags == ()
    assert first.raw.endswith("</output>\n")
    assert "[symbiont]" not in first.raw
    assert first.exit_code == 1
    assert ours.kind == Kind.TOOL_RESULT
    assert ours.tags == ("symbiont-output",)
    assert ours.raw.startswith("[symbiont]\nThis file was reworked twice")
    assert all(r.tags == () for r in out if r is not ours)


def test_zero_or_two_actions_are_agent_turns_and_the_notice_is_kept():
    out = list(read_open_swe_traces(FIXTURES / "format_errors.jsonl", PROJECT))
    assert [r.kind for r in out] == [
        Kind.USER_TURN,
        Kind.AGENT_TURN,
        Kind.TOOL_RESULT,
        Kind.AGENT_TURN,
        Kind.TOOL_RESULT,
        Kind.AGENT_TURN,
        Kind.COMMAND,
    ]
    assert out[1].raw == "I think the bug is in the tokenizer."
    assert out[2].raw.startswith("Please always provide EXACTLY ONE action")
    assert "```bash\nls\n```" in out[3].raw
    assert "Found 2 actions" in out[4].raw
    assert out[6].exit_code == 0


def test_append_redirect_and_tee_are_edits():
    out = list(read_open_swe_traces(FIXTURES / "writes.jsonl", PROJECT))
    append, tee, quiet = [r for r in out if r.command]
    assert (append.kind, append.files) == (Kind.EDIT, ("notes.txt",))
    assert (tee.kind, tee.files) == (Kind.EDIT, ("config.py", "settings.py"))
    assert (quiet.kind, quiet.files) == (Kind.COMMAND, ())


# --- lines the reader cannot parse are named, never skipped -----------------


def write_lines(tmp_path, lines):
    path = tmp_path / "trajectories.jsonl"
    path.write_text("".join(line + "\n" for line in lines))
    return path


def fixture_rows():
    return [json.loads(line) for line in RUNS.read_text().splitlines()]


def test_malformed_line_raises_readerror_with_line(tmp_path):
    good = RUNS.read_text().splitlines()
    path = write_lines(tmp_path, [good[0], good[1][:120]])
    with pytest.raises(ReadError) as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 2
    assert err.value.path == path
    assert str(path) in str(err.value)


def test_missing_instance_id_raises_readerror(tmp_path):
    row = fixture_rows()[0]
    del row["instance_id"]
    with pytest.raises(ReadError, match="instance_id"):
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))


def test_non_object_message_after_assistant_raises_readerror(tmp_path):
    row = fixture_rows()[0]
    row["messages"][3] = "not a message"
    with pytest.raises(ReadError, match="must be an object") as err:
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))
    assert err.value.line_no == 1
