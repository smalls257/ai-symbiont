import re

import pytest

from symbiont.core.memory_note import (
    INSTRUCTION,
    MAX_NOTE_CHARS,
    InvalidNoteError,
    lesson_line,
    note_line,
    note_request,
    recall_request,
    training_pairs,
)
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_cli.py", "ModuleNotFoundError"))
REWORK = Signature(Signal.REWORKED_EDIT, ("src/cli.py",))
FORBIDDEN = re.compile(r"score|feature|threshold|risk|\d\.\d", re.IGNORECASE)


def lesson(signature=FAILED, resolution=("ran `pip install -e .`",)):
    return Lesson(
        pain_point=PainPoint(signature, "s1", 3, (("s1", 3),)),
        quote="$ pytest tests/test_cli.py\nModuleNotFoundError: No module named 'demo'",
        resolution=resolution,
        unresolved_because=None if resolution else "no later command passed",
        spark_safe=True,
        sources=(("s1", 3),),
    )


def test_note_request_is_domain_prose_with_the_instruction():
    prompt = note_request("demo", FAILED)
    assert prompt.startswith("In demo, `pytest tests/test_cli.py` failed with ModuleNotFoundError")
    assert prompt.endswith(INSTRUCTION)
    assert not FORBIDDEN.search(prompt)


def test_lesson_line_is_three_labeled_parts_and_validates():
    line = lesson_line(lesson())
    assert line == (
        "Happened: `pytest tests/test_cli.py` failed with ModuleNotFoundError"
        " -> Resolved: you ran `pip install -e .`"
        " -> Check: run `pytest tests/test_cli.py` and confirm it passes before moving on"
    )
    assert note_line(line) == line


def test_an_unresolved_lesson_says_no_fix_was_found():
    assert "Resolved: no fix was found in the history" in lesson_line(lesson(REWORK, ()))


def test_every_lesson_line_validates_for_every_signal():
    signatures = [
        FAILED,
        REWORK,
        Signature(Signal.REVIEW_FLAG, ("a.py",)),
        Signature(Signal.CORRECTION, ("-", "use tabs")),
        Signature(Signal.LOOP, ("command", "make")),
        Signature(Signal.BLAST_RADIUS, ("a.py", "b.py")),
    ]
    for signature in signatures:
        note_line(lesson_line(lesson(signature)))


def test_training_pairs_share_one_answer_and_the_live_prompt():
    pairs = training_pairs("demo", lesson())
    assert pairs[0].prompt == note_request("demo", FAILED)
    assert {pair.line for pair in pairs} == {lesson_line(lesson())}
    assert all(pair.prompt.endswith(INSTRUCTION) for pair in pairs)
    assert pairs[1].prompt == recall_request(
        "demo", "What went wrong last time with `pytest tests/test_cli.py`?"
    )


@pytest.mark.parametrize(
    ("reply", "says"),
    [
        ("", "empty"),
        ("   \n ", "empty"),
        ("Happened: a -> Resolved: b\nCheck: c", "more than one line"),
        ("Happened: a -> Resolved: b", "2 parts"),
        ("Happened: a -> Resolved:  -> Check: c", "Resolved"),
        ("What: a -> Resolved: b -> Check: c", "Happened"),
        ("Happened: " + "x" * MAX_NOTE_CHARS + " -> Resolved: b -> Check: c", "over"),
    ],
)
def test_a_reply_outside_the_form_raises_without_quoting_it(reply, says):
    with pytest.raises(InvalidNoteError, match=says) as raised:
        note_line(reply)
    assert "x" * 20 not in str(raised.value)


def test_surrounding_whitespace_is_not_a_second_line():
    assert note_line("  Happened: a -> Resolved: b -> Check: c\n") == (
        "Happened: a -> Resolved: b -> Check: c"
    )
