from record_builders import replace_text, review, session
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.review_flag import find_review_flags

DIALECT = "sqlglot/dialects/dialect.py"
HUNK = (
    "@@ -210,6 +210,8 @@ class Dialect:\n"
    "     def cast_sql(self, expression):\n"
    "+        if expression.args.get('safe'):\n"
    "+            return self.func('TRY_CAST', expression.this)\n"
)


def test_review_comment_then_rework():
    s = session(
        review(DIALECT, HUNK, "This changes every dialect; move it to DuckDB."),
        replace_text(
            DIALECT,
            "        if expression.args.get('safe'):\n"
            "            return self.func('TRY_CAST', expression.this)",
            "",
        ),
    )
    assert find_review_flags(s) == [
        PainPoint(
            signature=Signature(Signal.REVIEW_FLAG, (DIALECT,)),
            session_id="s1",
            step=0,
            record_refs=(("s1", 0), ("s1", 1)),
        )
    ]


def test_review_comment_left_standing_is_not_a_flag():
    s = session(
        review(DIALECT, HUNK, "nit: maybe a docstring?"),
        replace_text(DIALECT, "def unrelated(self):", "def unrelated(self, x):"),
    )
    assert find_review_flags(s) == []


def test_change_to_the_same_text_in_another_file_is_not_a_flag():
    s = session(
        review(DIALECT, HUNK, "move it"),
        replace_text("sqlglot/dialects/duckdb.py", "        if expression.args.get('safe'):", ""),
    )
    assert find_review_flags(s) == []


def test_change_before_the_comment_is_not_a_flag():
    s = session(
        replace_text(DIALECT, "        if expression.args.get('safe'):", ""),
        review(DIALECT, HUNK, "move it"),
    )
    assert find_review_flags(s) == []
