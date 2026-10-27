"""Blast radius: a change made without looking at the places it affects, and
a test of one of those places broke. sqlglot's known trap: change the base
dialect, never open duckdb.py, and tests/dialects/test_duckdb.py fails."""

from record_builders import edit, run, session, view
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.blast_radius import find_blast_radius

DIALECT = "sqlglot/dialects/dialect.py"
DUCKDB = "sqlglot/dialects/duckdb.py"
TEST_DUCKDB = "tests/dialects/test_duckdb.py"
# references[path] = files that import or name `path`.
REFERENCES = {
    DIALECT: frozenset({DUCKDB}),
    DUCKDB: frozenset({TEST_DUCKDB}),
    "sqlglot/parser.py": frozenset({"sqlglot/tokens.py"}),
    "sqlglot/tokens.py": frozenset({"tests/test_tokens.py"}),
}
PYTEST_FAILED = (
    "FAILED tests/dialects/test_duckdb.py::TestDuckDB::test_cast - AssertionError\n1 failed"
)


def test_blast_radius_when_dependent_unread_and_test_fails():
    s = session(
        edit("sqlglot/parser.py"),
        run(
            "python -m pytest tests/test_tokens.py -q",
            1,
            "FAILED tests/test_tokens.py::TestTokens::test_x - KeyError",
        ),
    )
    assert find_blast_radius(s, REFERENCES) == [
        PainPoint(
            signature=Signature(Signal.BLAST_RADIUS, ("sqlglot/parser.py", "sqlglot/tokens.py")),
            session_id="s1",
            step=0,
            record_refs=(("s1", 0), ("s1", 1)),
        )
    ]


def test_no_blast_radius_when_dependent_was_read():
    s = session(
        view("sqlglot/tokens.py"),
        edit("sqlglot/parser.py"),
        run("pytest tests/test_tokens.py", 1, "FAILED tests/test_tokens.py::t"),
    )
    assert find_blast_radius(s, REFERENCES) == []


def test_dependent_looked_at_through_a_shell_command_counts_as_read():
    s = session(
        run(f"grep -n Dialect {DUCKDB}", 0, "12:class DuckDB(Dialect):"),
        edit(DIALECT),
        run("pytest tests/dialects", 1, PYTEST_FAILED),
    )
    assert find_blast_radius(s, REFERENCES) == []


def test_reading_the_dependent_only_after_the_failure_is_too_late():
    s = session(edit(DIALECT), run("pytest tests/dialects", 1, PYTEST_FAILED), view(DUCKDB))
    (pain,) = find_blast_radius(s, REFERENCES)
    assert pain.signature.key == (DIALECT, DUCKDB)


def test_failure_before_the_edit_is_not_blast_radius():
    s = session(run("pytest tests/dialects", 1, PYTEST_FAILED), edit(DIALECT))
    assert find_blast_radius(s, REFERENCES) == []


def test_unrelated_test_failure_is_not_blast_radius():
    s = session(
        edit(DIALECT),
        run("pytest tests/test_parser.py", 1, "FAILED tests/test_parser.py::TestParser::test_x"),
    )
    assert find_blast_radius(s, REFERENCES) == []


def test_failing_test_named_by_unittest_output():
    unittest_out = (
        "FAIL: test_cast (tests.dialects.test_duckdb.TestDuckDB.test_cast)\n"
        "AssertionError: 'TRY_CAST(x AS INT)' != 'CAST(x AS INT)'\n"
        "FAILED (failures=1)"
    )
    s = session(
        edit(DIALECT), run("python -m unittest tests.dialects.test_duckdb", 1, unittest_out)
    )
    (pain,) = find_blast_radius(s, REFERENCES)
    assert pain.signature.key == (DIALECT, DUCKDB)


def test_failing_test_named_by_absolute_path():
    out = "FAILED /workspace/tobymao__sqlglot/tests/dialects/test_duckdb.py::TestDuckDB::test_cast"
    s = session(edit(DIALECT), run("pytest /workspace/tobymao__sqlglot/tests/dialects", 1, out))
    assert [p.signature.key for p in find_blast_radius(s, REFERENCES)] == [(DIALECT, DUCKDB)]


def test_failing_test_file_that_directly_references_the_edit():
    refs = {DIALECT: frozenset({"tests/dialects/test_dialect.py"})}
    out = "FAILED tests/dialects/test_dialect.py::TestDialect::test_enum"
    s = session(edit(DIALECT), run("pytest tests/dialects/test_dialect.py", 1, out))
    (pain,) = find_blast_radius(s, refs)
    assert pain.signature.key == (DIALECT, "tests/dialects/test_dialect.py")


def test_one_pain_point_per_edit_and_dependent():
    s = session(
        edit(DIALECT),
        run("pytest tests/dialects", 1, PYTEST_FAILED),
        edit(DIALECT),
        run("pytest tests/dialects", 1, PYTEST_FAILED),
    )
    assert len(find_blast_radius(s, REFERENCES)) == 1


def test_rejected_edit_has_no_blast_radius():
    s = session(edit(DIALECT, exit_code=1), run("pytest tests/dialects", 1, PYTEST_FAILED))
    assert find_blast_radius(s, REFERENCES) == []
