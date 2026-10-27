"""Reworked edits are found by content: OpenHands records no line numbers for
an edit, so "the same lines changed again" means a later edit takes out text
an earlier edit put in."""

from record_builders import edit, replace_text, run, session
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.signals.reworked_edit import find_reworked_edits

PARSER = "sqlglot/parser.py"


def test_edit_then_reedit_same_lines():
    s = session(
        replace_text(
            PARSER, "    return self._parse_id()", "    return self._parse_id_var(any_token=True)"
        ),
        run("pytest tests/test_parser.py", 1, "AssertionError"),
        replace_text(
            PARSER,
            "    return self._parse_id_var(any_token=True)",
            "    return self._parse_id_var()",
        ),
    )
    assert find_reworked_edits(s) == [
        PainPoint(
            signature=Signature(Signal.REWORKED_EDIT, (PARSER,)),
            session_id="s1",
            step=2,
            record_refs=(("s1", 0), ("s1", 2)),
        )
    ]


def test_reedit_other_lines_not_rework():
    s = session(
        replace_text(PARSER, "    return self._parse_id()", "    return self._parse_id_var()"),
        replace_text(PARSER, "def _parse_table(self):", "def _parse_table(self, schema=False):"),
    )
    assert find_reworked_edits(s) == []


def test_same_text_in_another_file_is_not_rework():
    s = session(
        replace_text(PARSER, "x = 1", "x = compute_offset(node)"),
        replace_text("sqlglot/generator.py", "x = compute_offset(node)", "x = 2"),
    )
    assert find_reworked_edits(s) == []


def test_indentation_change_still_counts_as_rework():
    s = session(
        replace_text(PARSER, "pass", "if token.text == 'TRY_CAST':"),
        replace_text(
            PARSER,
            "    if token.text == 'TRY_CAST':",
            "    if token.token_type == TokenType.TRY_CAST:",
        ),
    )
    assert [p.step for p in find_reworked_edits(s)] == [1]


def test_punctuation_only_lines_do_not_link_edits():
    """`)` and `}` appear everywhere; sharing one proves nothing."""
    s = session(
        replace_text(PARSER, "a(", "a(\n    b,\n)"),
        replace_text(PARSER, "c(\n)", "c()"),
    )
    assert find_reworked_edits(s) == []


def test_rejected_edits_neither_rework_nor_get_reworked():
    s = session(
        replace_text(PARSER, "x = 1", "x = compute_offset(node)", exit_code=1),
        replace_text(PARSER, "x = compute_offset(node)", "x = 2"),
    )
    assert find_reworked_edits(s) == []


def test_edit_without_content_is_not_judged():
    """An undo carries no diff: what it reverted is unknown, so it is not
    called rework on a guess."""
    s = session(
        replace_text(PARSER, "x = 1", "x = compute_offset(node)"),
        edit(PARSER, diff=None),
    )
    assert find_reworked_edits(s) == []


def test_one_pain_point_per_reworking_edit_citing_every_earlier_edit():
    s = session(
        replace_text(PARSER, "a = 1", "a = first_try()"),
        replace_text(PARSER, "b = 1", "b = second_try()"),
        replace_text(PARSER, "a = first_try()\nb = second_try()", "a, b = together()"),
    )
    (pain,) = find_reworked_edits(s)
    assert pain.record_refs == (("s1", 0), ("s1", 1), ("s1", 2))


def test_rework_across_sessions_of_one_chain():
    """Callers may pass the sessions of one task chain in order; the rework
    pain point belongs to the session that reworked."""
    first = session(replace_text(PARSER, "x = 1", "x = compute_offset(node)"))
    second = [
        r.__class__(**{**r.__dict__, "session_id": "s2"})
        for r in session(replace_text(PARSER, "x = compute_offset(node)", "x = 2"))
    ]
    (pain,) = find_reworked_edits(first + second)
    assert (pain.session_id, pain.record_refs) == ("s2", (("s1", 0), ("s2", 0)))
