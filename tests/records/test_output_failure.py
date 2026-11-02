import pytest

from symbiont.records.output_failure import exit_code_with_output, shows_failure

PYTEST_RED = (
    "F.\n=== short test summary info ===\n"
    "FAILED tests/test_a.py::test_x - assert 1 == 2\n"
    "1 failed, 3 passed in 0.42s\n"
)
PYTEST_GREEN = "....\n4 passed in 0.31s\n"
PIPED = "uv run pytest -q 2>&1 | head -n 200"


@pytest.mark.parametrize(
    "output",
    [
        PYTEST_RED,
        "2 errors in 0.10s",
        "tests/a.py::test_x FAILED [ 50%]",
        "FAILED (failures=2)\n",
        "Tests:       1 failed, 4 passed, 5 total\n",
        " Tests  2 failed | 3 passed (5)\n",
        "  2 failing\n",
        "src/a.ts(3,1): error TS2322: Type 'x' is not assignable\n",
        "test result: FAILED. 1 passed; 1 failed\n",
        "--- FAIL: TestThing (0.00s)\n",
        'Traceback (most recent call last):\n  File "a.py", line 1\nValueError: bad\n',
    ],
)
def test_runner_failure_summaries_are_recognized(output):
    assert shows_failure(output)


@pytest.mark.parametrize(
    "output",
    [
        PYTEST_GREEN,
        "tests/test_login.py::test_failed_login PASSED\n1 passed in 0.1s\n",
        "Tests:       5 passed, 5 total\n",
        "0 failed expected; all good\n",
        "Traceback (most recent call last):\n ValueError: caught\nrecovered, 3 passed\n",
        "",
    ],
)
def test_passing_or_unrelated_output_is_not_a_failure(output):
    assert not shows_failure(output)


def test_a_piped_failing_run_reported_as_success_becomes_exit_1():
    assert exit_code_with_output(PIPED, PYTEST_RED, 0) == 1
    assert exit_code_with_output("pytest -q | tail -5", PYTEST_RED, None) == 1
    assert exit_code_with_output("npm test 2>&1 | tee out.log", "Tests: 1 failed, 1 total", 0) == 1


def test_a_piped_passing_run_stays_a_success():
    assert exit_code_with_output(PIPED, PYTEST_GREEN, 0) == 0


def test_unreported_code_stays_unknown_when_output_is_clean():
    assert exit_code_with_output(PIPED, PYTEST_GREEN, None) is None


def test_an_unpiped_command_is_left_alone_even_if_its_output_mentions_failure():
    assert exit_code_with_output("cat report.txt", PYTEST_RED, 0) == 0
    assert exit_code_with_output("pytest -q", PYTEST_RED, 0) == 0


def test_a_pipe_into_something_other_than_a_filter_is_left_alone():
    assert exit_code_with_output("pytest -q | grep passed", PYTEST_RED, 0) == 0


def test_a_logical_or_is_not_a_pipe():
    assert exit_code_with_output("pytest -q || head x", PYTEST_RED, 0) == 0


def test_a_reported_failure_stands():
    assert exit_code_with_output(PIPED, PYTEST_GREEN, 2) == 2
