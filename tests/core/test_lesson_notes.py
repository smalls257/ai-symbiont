"""Lessons render as what happened, how it was resolved, and the check to run.

Hand-written lessons only. The failures guarded against are a Leaky Narrative
(a score or feature name in a note) and a Silent Fallback (a note claiming a
fix the history does not show).
"""

import re

from symbiont.core.notes import NoteKind, render, render_lesson
from symbiont.core.recall import relevant_lessons
from symbiont.core.slot import Decision
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_parser.py", "ModuleNotFoundError"))
FORBIDDEN = re.compile(r"score|KC|feature|threshold|risk", re.IGNORECASE)


QUOTE = "$ pytest tests/test_parser.py\nNo module named 'yaml'"


def lesson(signature=FAILED, resolution=("ran `pip install pyyaml`", "ran `pytest`"), step=1):
    pain = PainPoint(signature, "s1", step, (("s1", step),))
    return Lesson(
        pain_point=pain,
        quote=QUOTE if signature == FAILED else "edited the index page",
        resolution=resolution,
        unresolved_because=None if resolution else "no later command passed",
        spark_safe=True,
        sources=(("s1", step),),
    )


def test_a_lesson_reads_as_happened_resolved_check():
    note = render_lesson(lesson())
    assert note == (
        "What happened: `pytest tests/test_parser.py` failed with ModuleNotFoundError. "
        "Last time it was resolved when you ran `pip install pyyaml`, then ran `pytest`. "
        "Check: run `pytest tests/test_parser.py` and confirm it passes before moving on."
    )


def test_an_unresolved_lesson_says_no_fix_was_found_rather_than_inventing_one():
    note = render_lesson(lesson(resolution=()))
    assert "No fix was found in the history." in note and "resolved when" not in note


def test_every_signal_renders_as_prose_with_a_check():
    keys = {
        Signal.FAILED_COMMAND: FAILED.key,
        Signal.REWORKED_EDIT: ("a.py",),
        Signal.REVIEW_FLAG: ("a.py",),
        Signal.CORRECTION: ("-", "use the fixture"),
        Signal.LOOP: ("command", "pytest"),
        Signal.BLAST_RADIUS: ("a.py", "b.py"),
    }
    for signal, key in keys.items():
        note = render_lesson(lesson(Signature(signal, key)))
        assert note.startswith("What happened: ") and "Check: " in note
        assert not FORBIDDEN.search(note), note


def test_a_warning_backed_by_a_lesson_adds_the_fix_and_the_check():
    backing = lesson()
    decision = Decision(FAILED, (backing.pain_point,), (), None)
    (note,) = render(decision, kinds=[NoteKind.WARN], lessons=[backing])
    assert note.startswith("This command has failed once before")
    assert "pip install pyyaml" in note and "Check: run `pytest" in note


def test_a_warning_with_no_lesson_stays_the_plain_sentence():
    decision = Decision(FAILED, (lesson().pain_point,), (), None)
    (note,) = render(decision, kinds=[NoteKind.WARN])
    assert "Check:" not in note


def test_recall_finds_lessons_by_trouble_quote_or_fix():
    docs = Signature(Signal.REWORKED_EDIT, ("docs/index.md",))
    parser, other = lesson(), lesson(docs, ("edited `docs/index.md`",), step=2)
    assert relevant_lessons("why did test_parser fail?", [other, parser]) == [parser]
    assert relevant_lessons("how was pyyaml fixed?", [other, parser]) == [parser]
    assert relevant_lessons("the index page", [other, parser]) == [other]
    assert relevant_lessons("zebra giraffe", [other, parser]) == []


def test_changes_alongside_are_said_to_have_happened_not_claimed_as_the_fix():
    from dataclasses import replace

    note = render_lesson(replace(lesson(), changed_alongside=("edited `docs/notes.md`",)))
    assert "you also edited `docs/notes.md`." in note
    assert "resolved when you ran `pip install pyyaml`, then ran `pytest`." in note
