from record_builders import edit, run, session, user
from symbiont.miner.mine import mine_session
from symbiont.miner.painpoint import Signal


def test_mine_session_runs_every_signal():
    s = session(
        user("fix TRY_CAST"),
        edit("sqlglot/dialects/dialect.py"),
        run(
            "pytest tests/dialects",
            1,
            "FAILED tests/dialects/test_duckdb.py::T::t - AssertionError",
        ),
        run(
            "pytest tests/dialects",
            1,
            "FAILED tests/dialects/test_duckdb.py::T::t - AssertionError",
        ),
        run(
            "pytest tests/dialects",
            1,
            "FAILED tests/dialects/test_duckdb.py::T::t - AssertionError",
        ),
        user("you broke dialect.py"),
    )
    references = {
        "sqlglot/dialects/dialect.py": frozenset({"sqlglot/dialects/duckdb.py"}),
        "sqlglot/dialects/duckdb.py": frozenset({"tests/dialects/test_duckdb.py"}),
    }
    signals = sorted({p.signature.signal for p in mine_session(s, references)})
    assert signals == sorted(
        {Signal.FAILED_COMMAND, Signal.LOOP, Signal.BLAST_RADIUS, Signal.CORRECTION}
    )


def _in_session(records, session_id):
    from dataclasses import replace

    return [replace(r, session_id=session_id) for r in records]


def test_mine_chain_no_longer_finds_rework_it_is_churn():
    from record_builders import replace_text
    from symbiont.miner.mine import mine_chain

    monday = _in_session(
        session(replace_text("sqlglot/parser.py", "x = 1", "x = compute_offset(node)")), "mon"
    )
    tuesday = _in_session(
        session(replace_text("sqlglot/parser.py", "x = compute_offset(node)", "x = 2")), "tue"
    )
    assert mine_chain([monday, tuesday], {}) == []
    assert mine_chain([monday, tuesday], {}) == mine_session(monday, {}) + mine_session(tuesday, {})


def test_mine_chain_counts_no_in_session_rework_either():
    from record_builders import replace_text
    from symbiont.miner.mine import mine_chain

    monday = session(
        replace_text("sqlglot/parser.py", "x = 1", "x = compute_offset(node)"),
        replace_text("sqlglot/parser.py", "x = compute_offset(node)", "x = 2"),
    )
    assert mine_chain([monday], {}) == []
    assert mine_session(monday, {}) == []
