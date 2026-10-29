"""Route B nightly rows: every answer quotes the stored lesson; no fix means no action row."""

import re

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.trained import lesson_id
from symbiont.routeb.lesson_rows import (
    agent_system,
    memory_system,
    training_rows,
    verify_questions,
)

FAILED = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_cli.py", "ModuleNotFoundError"))
CORRECTED = Signature(Signal.CORRECTION, ("-", "use uv, not pip"))
FORBIDDEN = re.compile(r"score|feature|threshold|activation|\d\.\d", re.IGNORECASE)


def lesson(signature=FAILED, resolution=("ran `pip install -e .`",), step=3):
    return Lesson(
        pain_point=PainPoint(signature, "s1", step, (("s1", step),)),
        quote="$ pytest tests/test_cli.py\nModuleNotFoundError: No module named 'demo'",
        resolution=resolution,
        unresolved_because=None if resolution else "no later command passed",
        spark_safe=False,
        sources=(("s1", step),),
    )


def test_a_resolved_lesson_gives_two_cards_and_one_corrected_action():
    rows = training_rows("demo", [lesson()])
    assert [row.kind for row in rows] == ["self-study", "self-study", "action"]
    card = rows[0].messages[2]["content"]
    assert card.startswith("What happened: `pytest tests/test_cli.py` failed with ModuleNotFound")
    assert "you ran `pip install -e .`" in card and rows[1].messages[2]["content"] == card
    action = rows[2].messages
    assert action[0]["content"] == agent_system("demo")
    assert action[1]["content"] == (
        "Task in demo: you are about to run `pytest tests/test_cli.py`. What is your next action?"
    )
    assert action[2]["content"].startswith("Last time `pytest tests/test_cli.py` failed")
    assert "resolved when you ran `pip install -e .`" in action[2]["content"]


def test_a_lesson_with_no_fix_teaches_no_made_up_action():
    rows = training_rows("demo", [lesson(resolution=())])
    assert [row.kind for row in rows] == ["self-study", "self-study"]
    assert "No fix was found in the history." in rows[0].messages[2]["content"]


def test_rows_are_domain_prose_under_the_memory_system():
    rows = training_rows("demo", [lesson(), lesson(CORRECTED, step=7)])
    for row in rows:
        assert row.lesson_id in {lesson_id(lesson()), lesson_id(lesson(CORRECTED, step=7))}
        for message in row.messages:
            assert not FORBIDDEN.search(message["content"]), message["content"]
    assert rows[3].messages[0]["content"] == memory_system("demo")
    assert "the developer's request." in rows[5].messages[1]["content"]


def test_verify_questions_use_a_wording_no_training_row_uses():
    lessons = [lesson(), lesson(CORRECTED, step=7)]
    asked = {row.messages[1]["content"] for row in training_rows("demo", lessons)}
    questions = verify_questions("demo", lessons)
    assert [q.lesson_id for q in questions] == [lesson_id(x) for x in lessons]
    assert questions[0].text == (
        "Before I touch `pytest tests/test_cli.py` in demo, what should I know?"
    )
    assert not {q.text for q in questions} & asked
