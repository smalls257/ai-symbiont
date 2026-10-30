from record_builders import edit, run, say, session
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.failed_command import find_failed_commands

PYTEST_IMPORT_ERROR = (
    "tests/dialects/test_duckdb.py:3: in <module>\n"
    "E   ImportError: cannot import name 'ArraySort' from 'sqlglot.expressions'\n"
    "ERROR tests/dialects/test_duckdb.py\n"
    "1 error in 0.31s"
)


def test_nonzero_exit_is_pain_point():
    s = session(
        say("run the tests"),
        run("python -m pytest tests/dialects/test_duckdb.py -q", 1, PYTEST_IMPORT_ERROR),
        run("python -m pytest tests/dialects/test_duckdb.py -q", 0, "12 passed"),
    )
    assert find_failed_commands(s) == [
        PainPoint(
            signature=Signature(
                Signal.FAILED_COMMAND, ("pytest", "tests/dialects/test_duckdb.py", "ImportError")
            ),
            session_id="s1",
            step=1,
            record_refs=(("s1", 1),),
        )
    ]


def test_error_class_in_key():
    output = (
        "Traceback\n  ValueError: first\nduring handling\n"
        "sqlglot.errors.ParseError: Invalid expression"
    )
    (pain,) = find_failed_commands(session(run("python reproduce.py", 1, output)))
    assert pain.signature.key == ("python", "reproduce.py", "ParseError")


def test_exit_code_in_key_when_no_error_class():
    (pain,) = find_failed_commands(session(run("make lint", 2, "make: *** [lint] Error 2")))
    assert pain.signature.key == ("make", "-", "exit 2")


def test_unknown_exit_code_is_not_a_failure():
    assert find_failed_commands(session(run("pytest", None, ""))) == []


def test_rejected_edit_is_not_a_failed_command():
    assert find_failed_commands(session(edit("sqlglot/parser.py", exit_code=1))) == []


# --- exit 1 as an answer ------------------------------------------------------
# grep, diff and test use exit 1 to answer "no match", "files differ", "false".
# Counting that as a failure would mine every empty search as a mistake.


def test_search_with_no_match_is_not_a_failure():
    s = session(
        run('grep -rn "def parse_json" sqlglot/', 1, ""),
        run("rg ArraySort sqlglot/expressions.py", 1, ""),
        run('git grep -n "TRY_CAST" -- sqlglot', 1, ""),
    )
    assert find_failed_commands(s) == []


def test_search_that_errored_is_a_failure():
    (pain,) = find_failed_commands(
        session(run("grep -n foo missing.py", 2, "grep: missing.py: No such file or directory"))
    )
    assert pain.signature.key == ("grep", "missing.py", "exit 2")


def test_diff_and_test_exit_1_are_answers():
    s = session(
        run("diff -u a.sql b.sql", 1, "--- a.sql\n+++ b.sql"),
        run("[ -f sqlglot/dialects/duckdb.py ]", 1, ""),
        run("test -d build", 1, ""),
    )
    assert find_failed_commands(s) == []


def test_exit_status_comes_from_the_last_pipeline_stage():
    s = session(
        run("cd /workspace/sqlglot && grep -rn TRY_CAST sqlglot/ | grep -v test", 1, ""),
        run("python -m pytest tests/ -q 2>&1 | grep FAILED", 1, ""),
    )
    assert find_failed_commands(s) == []


def test_search_after_a_real_program_is_still_a_failure():
    """In `pytest && grep`, exit 1 may be pytest's own: grep never ran."""
    (pain,) = find_failed_commands(
        session(run("python -m pytest tests/test_parser.py -q && grep -c ok log.txt", 1, ""))
    )
    assert pain.signature.key == ("pytest", "tests/test_parser.py", "exit 1")


def test_search_piped_into_a_real_program_is_judged_by_that_program():
    (pain,) = find_failed_commands(
        session(run("grep -l Dialect sqlglot/*.py | xargs python lint.py", 1, ""))
    )
    assert pain.signature.key == ("grep", "-", "exit 1")
