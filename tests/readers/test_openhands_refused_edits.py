"""A malformed editor call is the agent's mistake: kept as a refused edit, not a refused file."""

import json
import logging
from pathlib import Path

import pytest

from symbiont.miner.changes import applied_edit
from symbiont.readers.errors import ReadError
from symbiont.readers.openhands import read
from symbiont.records.schema import Kind
from symbiont.records.session_tags import CREATED_TAG

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openhands" / "two_sessions.jsonl"
PROJECT = "tobymao/sqlglot"
LOGGER = "symbiont.readers.openhands"
WORKSPACE = "/workspace/tobymao__sqlglot__unknown"


def first_row() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8").splitlines()[0])


def editor_call(row: dict) -> dict:
    for message in row["trajectory"]:
        for call in message.get("tool_calls") or []:
            if call["function"]["name"] == "str_replace_editor":
                return call["function"]
    raise AssertionError("fixture has no editor call")


def file_with(tmp_path, arguments: dict, rows: int = 1) -> Path:
    row = first_row()
    editor_call(row)["arguments"] = json.dumps(arguments)
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for _ in range(rows)))
    return path


def refused_edits(records):
    return [r for r in records if r.kind == Kind.EDIT and r.diff is None]


def test_unknown_command_is_a_refused_edit_and_later_rows_still_read(tmp_path):
    path = file_with(tmp_path, {"command": "delete", "path": f"{WORKSPACE}/a.py"})
    records = list(read(path, PROJECT))
    (refused,) = refused_edits(records)
    assert refused.files == ("a.py",)
    assert refused.exit_code == 1
    assert refused.diff is None
    assert records[-1].step > refused.step


def test_str_replace_without_old_str_is_a_refused_edit(tmp_path):
    path = file_with(tmp_path, {"command": "str_replace", "path": f"{WORKSPACE}/a.py"})
    (refused,) = refused_edits(list(read(path, PROJECT)))
    assert refused.exit_code == 1
    assert refused.diff is None


def test_refused_edit_is_not_an_applied_edit(tmp_path):
    path = file_with(tmp_path, {"command": "delete", "path": f"{WORKSPACE}/a.py"})
    (refused,) = refused_edits(list(read(path, PROJECT)))
    assert applied_edit(refused) is False


def test_refused_edit_keeps_the_observation_as_raw(tmp_path):
    path = file_with(tmp_path, {"command": "delete", "path": f"{WORKSPACE}/a.py"})
    (refused,) = refused_edits(list(read(path, PROJECT)))
    assert refused.raw.startswith("Here's the result")


def test_refused_edit_without_observation_describes_the_call(tmp_path):
    row = first_row()
    editor_call(row)["arguments"] = json.dumps({"command": "delete", "path": f"{WORKSPACE}/a.py"})
    row["trajectory"] = [m for m in row["trajectory"] if m["role"] != "tool"]
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(row) + "\n")
    (refused,) = refused_edits(list(read(path, PROJECT)))
    assert "'delete'" in refused.raw


def test_one_warning_per_file_with_the_count(tmp_path, caplog):
    path = file_with(tmp_path, {"command": "delete", "path": f"{WORKSPACE}/a.py"}, rows=2)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        list(read(path, PROJECT))
    warnings = [r for r in caplog.records if r.name == LOGGER]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == f"{path}: kept 2 malformed editor calls as refused edits"
    assert "a.py" not in warnings[0].getMessage()


def test_clean_file_logs_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        list(read(FIXTURE, PROJECT))
    assert [r for r in caplog.records if r.name == LOGGER] == []


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"command": "delete"}, "path"),
        ({"path": f"{WORKSPACE}/a.py"}, "command"),
    ],
)
def test_missing_path_or_command_still_refuses_the_file(tmp_path, arguments, needle):
    path = file_with(tmp_path, arguments)
    with pytest.raises(ReadError, match=needle):
        list(read(path, PROJECT))


def edited_file(tmp_path, arguments: dict, name: str):
    folder = tmp_path / name
    folder.mkdir()
    records = read(file_with(folder, arguments), PROJECT)
    return next(r for r in records if r.kind == Kind.EDIT)


def test_openhands_create_is_tagged_created_and_an_update_is_not(tmp_path):
    path = f"{WORKSPACE}/n.py"
    new = edited_file(tmp_path, {"command": "create", "path": path, "file_text": "x\n"}, "c")
    replace = {"command": "str_replace", "path": path, "old_str": "a", "new_str": "b"}
    old = edited_file(tmp_path, replace, "r")
    assert CREATED_TAG in new.tags
    assert CREATED_TAG not in old.tags
