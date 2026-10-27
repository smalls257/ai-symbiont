import json
from pathlib import Path

import pytest

from symbiont.readers import READERS
from symbiont.readers.errors import ReadError
from symbiont.readers.openhands import read
from symbiont.records.schema import Kind

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openhands" / "two_sessions.jsonl"
PROJECT = "tobymao/sqlglot"


@pytest.fixture(scope="module")
def records():
    return list(read(FIXTURE, PROJECT))


def session(records, trajectory_id):
    return [r for r in records if r.session_id == trajectory_id]


def of_kind(records, kind):
    return [r for r in records if r.kind == kind]


def test_registered_under_harness_name():
    assert READERS["openhands"] is read


def test_str_replace_editor_becomes_edit(records):
    edits = of_kind(session(records, "traj-duckdb-array-sort"), Kind.EDIT)
    first = edits[0]
    assert first.files == ("sqlglot/dialects/duckdb.py",)
    assert ' TRANSFORMS = {\n+    exp.ArraySort: rename_func("ARRAY_SORT"),\n }\n' in first.diff
    assert first.diff.startswith(
        "--- a/sqlglot/dialects/duckdb.py\n+++ b/sqlglot/dialects/duckdb.py\n"
    )
    assert first.exit_code == 0


def test_rejected_edit_is_marked_failed_and_keeps_tool_text(records):
    rejected = of_kind(session(records, "traj-duckdb-array-sort"), Kind.EDIT)[-1]
    assert "-def _missing(self):\n+def _present(self):\n" in rejected.diff
    assert rejected.exit_code == 1
    assert rejected.raw.startswith("ERROR:\nNo replacement was performed")


def test_create_and_insert_diffs(records):
    created, inserted = of_kind(session(records, "traj-tokens-comment"), Kind.EDIT)
    assert created.files == ("reproduce.py",)
    assert created.diff.startswith("--- /dev/null\n+++ b/reproduce.py\n")
    assert "+import sqlglot\n" in created.diff
    assert inserted.files == ("sqlglot/tokens.py",)
    assert "@@ -120,0 +121,1 @@\n+        self._add_comment_after_semicolon()\n" in inserted.diff


def test_view_becomes_read_of_repo_relative_path(records):
    reads = of_kind(records, Kind.READ)
    assert [r.files for r in reads] == [("sqlglot/dialects/duckdb.py",), ("sqlglot/tokens.py",)]
    assert reads[0].raw.startswith("Here's the result of running `cat -n`")


def test_cmd_run_exit_code(records):
    commands = of_kind(session(records, "traj-duckdb-array-sort"), Kind.COMMAND)
    assert [c.exit_code for c in commands] == [1, 0]
    failed = commands[0]
    assert failed.command.endswith("python -m pytest tests/dialects/test_duckdb.py -x -q")
    assert "ImportError: cannot import name 'ArraySort'" in failed.raw


def test_command_without_observation_has_unknown_exit_code(records):
    last = session(records, "traj-tokens-comment")[-1]
    assert last.kind == Kind.COMMAND
    assert last.exit_code is None
    assert last.raw == ""


def test_task_id_is_instance_id(records):
    assert {r.session_id: r.task_id for r in records} == {
        "traj-duckdb-array-sort": "tobymao__sqlglot-4001",
        "traj-tokens-comment": "tobymao__sqlglot-4123",
    }


def test_provenance_spark_safe_true(records):
    provenances = {r.provenance for r in records}
    assert len(provenances) == 1
    (provenance,) = provenances
    assert provenance.dataset == "nebius/SWE-rebench-openhands-trajectories"
    assert provenance.licence == "CC-BY-4.0"
    assert provenance.spark_safe is True


def test_turns_in_order_with_dense_steps(records):
    first = session(records, "traj-duckdb-array-sort")
    assert [r.step for r in first] == list(range(len(first)))
    assert [r.kind for r in first] == [
        Kind.USER_TURN,
        Kind.AGENT_TURN,
        Kind.READ,
        Kind.COMMAND,
        Kind.AGENT_TURN,
        Kind.EDIT,
        Kind.AGENT_TURN,
        Kind.EDIT,
        Kind.EDIT,
        Kind.AGENT_TURN,  # think
        Kind.COMMAND,
        Kind.AGENT_TURN,  # finish
    ]
    assert all(r.harness == "openhands" and r.project == PROJECT for r in records)


def test_user_issue_kept_verbatim(records):
    user = session(records, "traj-duckdb-array-sort")[0]
    assert user.kind == Kind.USER_TURN
    assert "<issue_description>\nDuckDB: `ARRAY_SORT` with a lambda" in user.raw


def test_think_and_finish_text_kept(records):
    turns = of_kind(session(records, "traj-duckdb-array-sort"), Kind.AGENT_TURN)
    assert turns[-2].raw == "The lambda argument order differs between dialects."
    assert turns[-1].raw == "ARRAY_SORT now transpiles with the lambda kept."


# --- lines the reader cannot parse are named, never skipped -----------------


def write_lines(tmp_path, lines):
    path = tmp_path / "trajectories.jsonl"
    path.write_text("".join(line + "\n" for line in lines))
    return path


def fixture_rows():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def test_malformed_line_raises_readerror_with_line(tmp_path):
    good = FIXTURE.read_text().splitlines()
    path = write_lines(tmp_path, [good[0], good[1][:200]])
    with pytest.raises(ReadError) as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 2
    assert err.value.path == path
    assert str(path) in str(err.value)


def test_unknown_tool_raises_readerror(tmp_path):
    row = fixture_rows()[0]
    row["trajectory"][2]["tool_calls"][0]["function"]["name"] = "browse_web"
    path = write_lines(tmp_path, [json.dumps(row)])
    with pytest.raises(ReadError, match="browse_web") as err:
        list(read(path, PROJECT))
    assert err.value.line_no == 1


def test_observation_for_unknown_call_raises_readerror(tmp_path):
    row = fixture_rows()[0]
    row["trajectory"][3]["tool_call_id"] = "call-nobody-made"
    path = write_lines(tmp_path, [json.dumps(row)])
    with pytest.raises(ReadError, match="call-nobody-made"):
        list(read(path, PROJECT))


def test_missing_instance_id_raises_readerror(tmp_path):
    row = fixture_rows()[1]
    del row["instance_id"]
    path = write_lines(tmp_path, [json.dumps(row)])
    with pytest.raises(ReadError, match="instance_id"):
        list(read(path, PROJECT))


def test_viewing_the_workspace_root_reads_the_repo_root(tmp_path):
    row = fixture_rows()[0]
    row["trajectory"][2]["tool_calls"][0]["function"]["arguments"] = json.dumps(
        {"command": "view", "path": "/workspace/tobymao__sqlglot__unknown"}
    )
    path = write_lines(tmp_path, [json.dumps(row)])
    reads = of_kind(list(read(path, PROJECT)), Kind.READ)
    assert reads[0].files == (".",)


def _view_row(arguments: dict) -> dict:
    row = fixture_rows()[0]
    row["trajectory"][2]["tool_calls"][0]["function"]["arguments"] = json.dumps(arguments)
    return row


def test_view_range_is_kept_on_the_read(records):
    reads = of_kind(records, Kind.READ)
    assert [r.line_range for r in reads] == [None, (1, 40)]


def test_view_range_to_end_of_file_is_kept_as_given(tmp_path):
    path = write_lines(
        tmp_path,
        [
            json.dumps(
                _view_row(
                    {
                        "command": "view",
                        "path": "/workspace/tobymao__sqlglot__unknown/sqlglot/parser.py",
                        "view_range": [900, -1],
                    }
                )
            )
        ],
    )
    (first,) = of_kind(list(read(path, PROJECT)), Kind.READ)[:1]
    assert first.line_range == (900, -1)


def test_malformed_view_range_raises_readerror(tmp_path):
    path = write_lines(
        tmp_path,
        [
            json.dumps(
                _view_row(
                    {
                        "command": "view",
                        "path": "/workspace/tobymao__sqlglot__unknown/sqlglot/parser.py",
                        "view_range": "1-40",
                    }
                )
            )
        ],
    )
    with pytest.raises(ReadError, match="view_range"):
        list(read(path, PROJECT))
