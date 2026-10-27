from record_builders import edit, run, say, session, user
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.correction import find_corrections

DIALECT = "sqlglot/dialects/dialect.py"
FAILED = "FAILED tests/dialects/test_duckdb.py::TestDuckDB::test_cast - AssertionError"


def test_labelled_correction():
    s = session(
        user("Fix TRY_CAST for duckdb"),
        edit(DIALECT),
        user(
            "No, don't change the base dialect.py, override it in DuckDB instead",
            tags=("correction",),
        ),
    )
    assert find_corrections(s) == [
        PainPoint(
            signature=Signature(
                Signal.CORRECTION,
                (DIALECT, "no don't change the base dialect.py override it"),
            ),
            session_id="s1",
            step=2,
            record_refs=(("s1", 2),),
        )
    ]


def test_rejection_label_counts_and_unnamed_file_is_dash():
    s = session(
        user("Fix it"),
        say("I will rewrite the tokenizer"),
        user("Stop, that's not what I asked", tags=("rejection",)),
    )
    (pain,) = find_corrections(s)
    assert pain.signature.key == ("-", "stop that's not what i asked")


def test_unlabelled_correction_after_failure():
    s = session(
        user("Fix TRY_CAST for duckdb"),
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("You broke duckdb, revert dialect.py and do it in the subclass"),
    )
    (pain,) = find_corrections(s)
    assert (pain.signature.key, pain.step) == (
        (DIALECT, "you broke duckdb revert dialect.py and do it"),
        3,
    )


def test_plain_followup_is_not_correction():
    s = session(
        user("Fix TRY_CAST for duckdb"),
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 0, "12 passed"),
        user("Great, now look at dialect.py for the snowflake case"),
    )
    assert find_corrections(s) == []


def test_followup_after_failure_not_naming_an_edited_file_is_not_correction():
    s = session(
        user("Fix TRY_CAST"),
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("Also add a changelog entry"),
    )
    assert find_corrections(s) == []


def test_failure_before_an_earlier_user_turn_does_not_carry_over():
    s = session(
        edit(DIALECT),
        run("pytest tests/dialects/test_duckdb.py", 1, FAILED),
        user("ok, keep going"),
        say("done"),
        user("dialect.py looks fine now"),
    )
    assert find_corrections(s) == []
