"""The judge sees byte-for-byte what plug round 4 scored it on.

The expected strings are the output of the research builder (plug/round3 fca5548:
`plug_situation.situation_of`, `lessons.Lesson.text`, `plug_judge.pair_prompt`, `JUDGE_SYSTEM`) for
the lesson below, pinned here because that code lives on the research branch.
"""

from symbiont.core.judge_format import JUDGE_SYSTEM, judge_input, judge_situation, judgeable
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature

COMMAND = "pytest tests/test_units.py -k wind"
ERROR = "NameError: name 'np' is not defined"
FIX = "python -m pytest tests/test_units.py -k wind"

SITUATION = (
    "Ran `pytest tests/test_units.py -k wind` in Unidata/MetPy (file tests/test_units.py). "
    "It failed: NameError: name 'np' is not defined"
)
LESSON_TEXT = (
    "In Unidata/MetPy, `pytest tests/test_units.py -k wind` failed with "
    "NameError: name 'np' is not defined; "
    "run `python -m pytest tests/test_units.py -k wind` instead."
)
RESEARCH_PAIR_PROMPT = (
    f"Situation:\n{SITUATION}\n\nLesson:\n{LESSON_TEXT}\n\nDoes this lesson apply?"
)
RESEARCH_SYSTEM = (
    "You decide whether one stored lesson applies to what a coding agent is doing now. "
    "Answer yes or no."
)


def product_lesson():
    signature = Signature(Signal.FAILED_COMMAND, ("pytest", "tests/test_units.py", "NameError"))
    pain = PainPoint(signature, "s", 1, (("s", 1),))
    return Lesson(pain, f"$ {COMMAND}\n{ERROR}", (f"ran `{FIX}`",), None, True, (("s", 1),))


def test_the_judge_input_is_byte_identical_to_the_research_builder():
    situation = judge_situation(COMMAND, "Unidata/MetPy", "tests/test_units.py", ERROR)
    fields = judgeable(product_lesson(), "Unidata__MetPy")
    assert situation == SITUATION
    assert judge_input(situation, fields) == RESEARCH_PAIR_PROMPT
    assert JUDGE_SYSTEM == RESEARCH_SYSTEM


def test_a_lesson_the_judge_never_saw_the_shape_of_is_not_judgeable():
    lesson = product_lesson()
    assert judgeable(Lesson(**{**lesson.__dict__, "resolution": ("edited `a.py`",)}), "p") is None
    assert judgeable(Lesson(**{**lesson.__dict__, "quote": "no dollar line"}), "p") is None
