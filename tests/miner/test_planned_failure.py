"""TDD red is not a mistake; a broken import or a test broken by an edit is.

Hand-written sessions. The failure guarded against is a Paper Tiger: a lesson that tells the
developer "this failed last time" about the red step they meant to take.
"""

from record_builders import edit, run, session, view
from symbiont.miner.planned_failure import ErrorKind, FailureKind, error_kind, failure_kind
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.records.schema import Record

ASSERTION = "FAILED tests/test_parser.py::test_new - assert 1 == 2\nE   assert 1 == 2"
IMPORT = "ImportError: cannot import name 'parse' from 'app.parser'"


def failing(command: str, output: str) -> Record:
    return run(command, 1, output)


def test_a_tdd_red_to_green_session_yields_no_pain_point():
    steps = session(
        edit("tests/test_parser.py"),
        failing("pytest tests/test_parser.py::test_new", ASSERTION),
        edit("app/parser.py"),
        run("pytest tests/test_parser.py::test_new", 0, "1 passed"),
    )
    assert find_failed_commands(steps) == []


def test_an_existing_test_broken_by_an_edit_yields_one():
    steps = session(
        edit("app/parser.py"),
        failing("pytest tests/test_parser.py", ASSERTION),
        edit("app/parser.py"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    assert len(find_failed_commands(steps)) == 1


def test_an_import_error_then_a_fix_yields_one_even_in_a_test_written_this_session():
    steps = session(
        edit("tests/test_parser.py"),
        failing("pytest tests/test_parser.py", IMPORT),
        edit("app/parser.py"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    assert len(find_failed_commands(steps)) == 1


def test_an_assertion_in_a_test_nobody_touched_this_session_is_a_mistake():
    steps = session(edit("app/parser.py"), failing("pytest tests/test_other.py", ASSERTION))
    assert failure_kind(steps[1], steps[:1]) is FailureKind.MISTAKE


def test_error_kinds_come_from_the_error_text():
    assert error_kind("AssertionError: x") is ErrorKind.ASSERTION
    assert error_kind("NameError: x\nAssertionError") is ErrorKind.CODE_ERROR
    assert error_kind("exit 2") is ErrorKind.UNNAMED


UNWRITTEN = "E   ImportError: cannot import name 'parse_dates' from 'mylib' (mylib/__init__.py)"
NUMPY = "E   ModuleNotFoundError: No module named 'numpy'"


def test_a_new_test_importing_a_not_yet_written_project_function_gives_no_lesson():
    steps = session(
        view("mylib/__init__.py"),
        edit("tests/test_dates.py"),
        failing("pytest tests/test_dates.py", UNWRITTEN),
        edit("mylib/dates.py"),
        run("pytest tests/test_dates.py", 0, "1 passed"),
    )
    assert find_failed_commands(steps) == []


def test_a_test_failing_on_a_missing_third_party_module_gives_a_lesson():
    steps = session(
        view("mylib/__init__.py"),
        edit("tests/test_dates.py"),
        failing("pytest tests/test_dates.py", NUMPY),
        run("pip install numpy", 0, "ok"),
        run("pytest tests/test_dates.py", 0, "1 passed"),
    )
    assert len(find_failed_commands(steps)) == 1
