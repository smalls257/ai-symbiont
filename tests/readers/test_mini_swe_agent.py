import json
from pathlib import Path

import pytest

from symbiont.readers import READERS
from symbiont.readers.errors import ReadError
from symbiont.readers.mini_swe_agent import read
from symbiont.records.schema import Kind

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mini_swe_agent"
RUNS = FIXTURES / "two_runs.jsonl"
PROJECT = "tobymao/sqlglot"


@pytest.fixture(scope="module")
def records():
    return list(read(RUNS, PROJECT))


def session(records, session_id):
    return [r for r in records if r.session_id == session_id]


def of_kind(records, kind):
    return [r for r in records if r.kind == kind]


def test_registered_under_harness_name():
    assert READERS["mini-swe-agent"] is read


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
    (provenance,) = {r.provenance for r in session(records, "mswe-sqlglot-1")}
    assert provenance.dataset == "open-swe-traces"
    assert provenance.spark_safe is True


def test_own_run_provenance(records):
    (provenance,) = {r.provenance for r in session(records, "glimmer-run-7")}
    assert provenance.dataset == "local-run"
    assert provenance.spark_safe is True


def test_task_id_is_instance_id(records):
    assert {r.session_id: r.task_id for r in records} == {
        "mswe-sqlglot-1": "tobymao__sqlglot-4001",
        "glimmer-run-7": "django__django-15000",
    }


def test_symbiont_output_is_tagged_not_mined():
    out = list(read(FIXTURES / "with_our_output.jsonl", PROJECT))
    tagged, plain = of_kind(out, Kind.COMMAND)
    assert tagged.tags == ("symbiont-output",)
    assert "[symbiont]" not in tagged.raw
    assert "reworked" not in tagged.raw
    assert "ImportError: cannot import name 'SortArray'" in tagged.raw
    assert tagged.exit_code == 1
    assert plain.tags == ()


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


def test_unknown_source_raises_readerror(tmp_path):
    row = fixture_rows()[0]
    row["source"] = "somewhere-else"
    with pytest.raises(ReadError, match="somewhere-else"):
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))


def test_two_actions_in_one_message_raise_readerror(tmp_path):
    row = fixture_rows()[0]
    row["messages"][2]["content"] += "\n\n```bash\nls\n```"
    with pytest.raises(ReadError, match="2 bash blocks"):
        list(read(write_lines(tmp_path, [json.dumps(row)]), PROJECT))
