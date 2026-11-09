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
    ONLY_UNRELATED_CHANGED,
    PASSED_RESPELLED,
    Resolution,
    Unresolved,
    reason_of,
    resolution_of,
)
from symbiont.miner.signals.failed_command import find_failed_commands

TEST = "pytest tests/test_parser.py -q"
BROKE = "E   ModuleNotFoundError: No module named 'yaml'\n1 error"
BROKE_IN_PARSER = "sqlglot/parser.py:12: in <module>\nE   NameError: name 'Token' is not defined"


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
        run(TEST, 1, BROKE_IN_PARSER),
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


def test_an_unrelated_command_passing_is_never_the_fix():
    records = session(
        run("git push origin main", 1, "rejected: non-fast-forward"), run("git status", 0, "")
    )
    assert resolve(records) == NO_LATER_SUCCESS


def test_the_same_command_passing_after_an_install_is_resolved():
    records = session(
        run("git push origin main", 1, "rejected"),
        run("git config pull.rebase true"),
        run("git push origin main", 0, ""),
    )
    assert steps_of(resolve(records)) == ["git config pull.rebase true", "git push origin main"]


def test_an_edit_to_a_file_the_failure_never_names_is_alongside_not_the_fix():
    records = session(
        run(TEST, 1, BROKE_IN_PARSER),
        edit("docs/changelog.md"),
        edit("sqlglot/parser.py"),
        run(TEST, 0, "3 passed"),
    )
    found = resolve(records)
    assert steps_of(found) == [("sqlglot/parser.py",), TEST]
    assert [r.files for r in found.alongside] == [("docs/changelog.md",)]


def test_only_unrelated_edits_before_an_unchanged_pass_is_no_fix_but_is_kept():
    records = session(run(TEST, 1, BROKE), edit("docs/changelog.md"), run(TEST, 0, "ok"))
    found = resolve(records)
    assert found.reason == ONLY_UNRELATED_CHANGED
    assert [r.files for r in found.alongside] == [("docs/changelog.md",)]


def test_another_npm_script_passing_is_not_the_fix():
    records = session(run("npm run build", 1, BROKE), run("npm run lint", 0, "ok"))
    assert resolve(records) == NO_LATER_SUCCESS


def test_the_same_npm_script_passing_later_still_matches():
    records = session(run("npm run build", 1, BROKE), run("npm run build", 0, "ok"))
    assert resolve(records) == NOTHING_CHANGED


@pytest.mark.parametrize("tool", ["docker run", "cargo run"])
def test_other_run_commands_compare_as_before(tool):
    records = session(run(f"{tool} app", 1, BROKE), run(f"{tool} other", 0, "ok"))
    assert steps_of(resolve(records)) == [f"{tool} other"]


@pytest.mark.parametrize("tool", ["npm", "yarn", "pnpm", "uv"])
def test_the_script_is_part_of_the_subcommand_for_script_runners(tool):
    records = session(run(f"{tool} run build", 1, BROKE), run(f"{tool} run lint", 0, "ok"))
    assert resolve(records) == NO_LATER_SUCCESS


# --- a shown fix, never a re-spelling ---------------------------------------------------

NO_TESTS = "collected 0 items\n\nno tests ran in 0.01s"
RED = "E   assert 1 == 2\n1 failed"


def test_a_pass_respelled_with_nothing_changed_is_unresolved_not_a_fix():
    records = session(run(TEST, 1, RED), run(f"{TEST} -x -k parse", 0, "1 passed"))
    found = resolve(records)
    assert reason_of(found) == PASSED_RESPELLED
    assert not isinstance(found, Resolution)


def test_a_corrected_invocation_is_a_known_fix():
    records = session(
        run("pytest tests/test_x.py", 5, NO_TESTS), run("pytest tests/dialects/test_x.py", 0, "ok")
    )
    assert steps_of(resolve(records)) == ["pytest tests/dialects/test_x.py"]


def test_an_edit_made_alongside_is_never_the_fix():
    records = session(run(TEST, 1, RED), edit("docs/changelog.md"), run(TEST, 0, "1 passed"))
    found = resolve(records)
    assert isinstance(found, Unresolved) and not isinstance(found, Resolution)
    assert [r.files for r in found.alongside] == [("docs/changelog.md",)]


def test_a_failure_is_resolved_from_its_own_session_only():
    failed = session(run(TEST, 1, RED))
    later = [replace(r, session_id="later") for r in session(run(TEST, 0, "1 passed"))]
    assert resolve(failed + later) == NO_LATER_SUCCESS


def test_a_pass_after_an_edit_to_the_failing_file_is_a_fix():
    records = session(run(TEST, 1, BROKE_IN_PARSER), edit("sqlglot/parser.py"), run(TEST, 0, "ok"))
    assert steps_of(resolve(records)) == [("sqlglot/parser.py",), TEST]


def test_a_pass_after_a_different_preparing_command_is_a_fix():
    records = session(run(TEST, 1, BROKE), run("pip install pyyaml"), run(TEST, 0, "ok"))
    assert steps_of(resolve(records)) == ["pip install pyyaml", TEST]


def test_each_lesson_is_resolved_against_its_own_session_records_only():
    from symbiont.miner.lessons import lessons_from

    one = session(run(TEST, 1, RED))
    other = [replace(r, session_id="s2") for r in session(run(TEST, 0, "1 passed"))]
    (lesson,) = lessons_from(find_failed_commands(one), one + other, frozenset())
    assert lesson.unresolved_because == NO_LATER_SUCCESS


def test_a_name_value_argument_is_not_the_subcommand():
    from symbiont.miner.resolutions import subcommand_of

    assert subcommand_of("make CC=gcc test") == "test"


def test_a_pass_chained_after_a_fix_step_is_the_same_attempt():
    from symbiont.miner.resolutions import later_success_of

    failed = run("git add a.ts", 128, "fatal: Unable to create '.git/index.lock': File exists.")
    s = session(failed, run("rm -f .git/index.lock && git add a.ts", 0, ""))
    assert later_success_of(s[0], s) is s[1]
    other = session(failed, run("rm -f .git/index.lock && git commit -m x", 0, ""))
    assert later_success_of(other[0], other) is None
