"""A passed check is a command that exited 0 and changed nothing: any language, any tool."""

import pytest

from record_builders import edit, run, view
from symbiont.miner.changes import passed_check


@pytest.mark.parametrize("command", ["pytest -q", "cargo test", "npm run build", "make check"])
def test_a_passing_command_that_changes_nothing_is_a_check(command):
    assert passed_check(run(command, 0, "ok"))


@pytest.mark.parametrize(
    "record",
    [
        run("pytest -q", 1, "boom"),
        run("pytest -q", None, ""),
        run("pip install requests", 0, "done"),
        run("mkdir build", 0, ""),
        edit("a.py"),
        view("a.py"),
    ],
)
def test_a_failure_an_unknown_status_a_change_or_a_non_command_is_not_a_check(record):
    assert not passed_check(record)
