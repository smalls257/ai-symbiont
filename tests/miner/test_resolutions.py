"""What resolved a failed command: what changed between the failure and the pass.

Hand-written records only. The failure guarded against is a Paper Tiger fix:
naming the passing re-run as the fix when the install or edit before it did the work.
"""

from dataclasses import replace

import pytest

from record_builders import edit, run, say, session, view
from symbiont.miner.changes import changes_workspace
from symbiont.miner.resolutions import (
    NO_LATER_SUCCESS,
    NOTHING_CHANGED,
    Resolution,
    resolution_of,
)
from symbiont.miner.signals.failed_command import find_failed_commands

TEST = "pytest tests/test_parser.py -q"
BROKE = "E   ModuleNotFoundError: No module named 'yaml'\n1 error"


def resolve(records):
    pain = find_failed_commands(records)[0]
    cited = [r for r in records if (r.session_id, r.step) in pain.record_refs]
    return resolution_of(pain, cited, records)


def steps_of(found):
    assert isinstance(found, Resolution), found
    return [r.command or r.files for r in found.steps]


def test_the_install_between_the_failure_and_the_pass_is_the_fix():
    records = session(
        run(TEST, 1, BROKE),
        run("ls sqlglot"),
        view("setup.py"),
        run("pip install pyyaml"),
        run(TEST, 0, "3 passed"),
    )
    assert steps_of(resolve(records)) == ["pip install pyyaml", TEST]


def test_edits_and_config_changes_between_are_the_fix_in_order():
    records = session(
        run(TEST, 1, BROKE),
        edit("sqlglot/parser.py"),
        run("git config core.autocrlf false"),
        run("grep -n yaml setup.py"),
        run(TEST, 0, "3 passed"),
    )
    assert steps_of(resolve(records)) == [
        ("sqlglot/parser.py",),
        "git config core.autocrlf false",
        TEST,
    ]


def test_a_different_way_of_running_it_is_a_fix_on_its_own():
    records = session(run(TEST, 1, BROKE), run(f"{TEST} --import-mode=importlib", 0, "ok"))
    assert steps_of(resolve(records)) == [f"{TEST} --import-mode=importlib"]


def test_the_same_command_passing_with_nothing_changed_is_not_a_fix():
    records = session(run(TEST, 1, BROKE), say("flaky?"), run(TEST, 0, "3 passed"))
    assert resolve(records) == NOTHING_CHANGED


def test_no_later_pass_means_no_resolution():
    records = session(run(TEST, 1, BROKE), run("pip install pyyaml"))
    assert resolve(records) == NO_LATER_SUCCESS


def test_a_failed_install_or_a_refused_edit_changed_nothing():
    records = session(
        run(TEST, 1, BROKE),
        run("pip install pyyaml", 1, "ERROR: no matching distribution"),
        edit("sqlglot/parser.py", exit_code=1),
        run(TEST, 0, "3 passed"),
    )
    assert resolve(records) == NOTHING_CHANGED


def test_changes_in_another_session_are_not_counted():
    failed = session(run(TEST, 1, BROKE), run(TEST, 0, "ok"))
    elsewhere = [replace(r, session_id="other") for r in session(run("pip install pyyaml"))]
    assert resolve(failed + elsewhere) == NOTHING_CHANGED


@pytest.mark.parametrize(
    ("command", "changes"),
    [
        ("uv add pyyaml", True),
        ("npm install", True),
        ("export PYTHONPATH=src", True),
        ("cd repo && mkdir build", True),
        ("cat setup.py", False),
        ("git status", False),
        ("python -m pytest tests", False),
    ],
)
def test_which_commands_change_the_workspace(command, changes):
    assert changes_workspace(run(command)) is changes
