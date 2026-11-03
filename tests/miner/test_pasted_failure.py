"""A prompt that pastes a red test run or red CI is a correction with the failing check named."""

from record_builders import session, user
from symbiont.miner.lessons import lessons_from
from symbiont.miner.painpoint import Signal
from symbiont.miner.pasted_failure import pasted_failure
from symbiont.miner.signals.correction import find_corrections

PYTEST = """Fix LOCALTIMESTAMP.

CI says:
=== FAILURES ===
E   AssertionError: a != b
E   - DATE_TRUNC('HOUR', x)
E   + CAST(DATE_TRUNC('HOUR', x) AS TIMESTAMP)
=== short test summary info ===
SUBFAILED[x -> duckdb] tests/dialects/test_snowflake.py::TestSnowflake::test_timestamps
1 failed, 2 passed in 0.29s
"""
JEST = """FAIL src/math.test.ts
  Expected: 4
  Received: 5
Tests:       1 failed, 3 passed, 4 total
"""
CARGO = """running 1 test
test adds ... FAILED
---- adds stdout ----
assertion `left == right` failed
  left: 4
 right: 5
test result: FAILED. 0 passed; 1 failed
"""
GO = "--- FAIL: TestAdd (0.00s)\n    add_test.go:12: got 5, want 4\nFAIL\n"


def test_pytest_names_the_check_its_file_and_the_diff():
    found = pasted_failure(PYTEST)
    assert found.check == "tests/dialects/test_snowflake.py::TestSnowflake::test_timestamps"
    assert found.file == "tests/dialects/test_snowflake.py"
    assert "- DATE_TRUNC('HOUR', x)" in found.excerpt


def test_jest_cargo_and_go():
    assert pasted_failure(JEST).check == "src/math.test.ts"
    assert pasted_failure(JEST).excerpt[-2:] == ("Expected: 4", "Received: 5")
    assert pasted_failure(CARGO).check == "adds"
    assert pasted_failure(CARGO).excerpt[-1] == "right: 5"
    assert pasted_failure(GO).check == "TestAdd"


def test_a_red_ci_sentence_without_a_log_is_a_generic_failure():
    found = pasted_failure("CI failed on this branch, please look")
    assert found.check == "ci" and found.excerpt


def test_an_ordinary_prompt_pastes_nothing():
    assert pasted_failure("Add a test_failed_login case and make CI faster") is None


def test_mining_a_prompt_with_ci_output_yields_a_correction_and_a_lesson_with_the_diff():
    records = session(user(PYTEST))
    (pain,) = find_corrections(records)
    assert pain.signature.signal is Signal.CORRECTION
    assert pain.signature.key[0] == "tests/dialects/test_snowflake.py"
    (lesson,) = lessons_from([pain], records)
    assert lesson.quote.startswith("CI reported")
    assert "+ CAST(DATE_TRUNC('HOUR', x) AS TIMESTAMP)" in lesson.expected_vs_actual


def test_our_own_delivered_note_is_not_a_pasted_failure():
    assert find_corrections(session(user(PYTEST, tags=("symbiont-output",)))) == []
