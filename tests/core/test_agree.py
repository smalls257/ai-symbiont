"""The agree rule: both the ranker and the judge must clear their frozen bars, else silence.

Hand-written lessons, no network: the judge is a function. The failures guarded against are a
Paper Tiger (a best guess shown whatever its score) and a Silent Fallback (a judge that cannot
answer read as "no").
"""

import pytest

from symbiont.core.agree import (
    JUDGE_MIN_P_YES,
    RANKER_MIN_SCORE,
    Verdict,
    agree,
    ranker_scores,
)
from symbiont.core.notes import render_lesson
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature


def lesson(index, fix="ran `pip install pyyaml`"):
    signature = Signature(Signal.FAILED_COMMAND, (f"tool{index}", f"module{index}", f"Oops{index}"))
    pain = PainPoint(signature, "s1", index, (("s1", index),))
    return Lesson(
        pain, f"$ tool{index} module{index}\nOops{index}", (fix,), None, True, (("s1", 1),)
    )


LESSONS = [lesson(index) for index in range(40)]
QUESTION = "tool7 module7 failed with Oops7 again, what now?"


def test_the_ranker_scores_a_lesson_by_idf_overlap_and_the_matching_one_wins():
    scores = ranker_scores(QUESTION, LESSONS)
    assert scores[7] == max(scores) and scores[7] >= RANKER_MIN_SCORE
    assert scores[0] == 0.0


def test_both_clearing_their_bars_shows_the_stored_note_verbatim():
    outcome = agree(QUESTION, "demo", LESSONS, lambda prompt: JUDGE_MIN_P_YES)
    assert outcome.verdict is Verdict.AGREED
    assert outcome.note == render_lesson(LESSONS[7])


def test_a_judge_under_its_bar_means_silence():
    outcome = agree(QUESTION, "demo", LESSONS, lambda prompt: JUDGE_MIN_P_YES - 0.01)
    assert (outcome.verdict, outcome.note) == (Verdict.JUDGE_TOO_LOW, None)


def test_a_weak_ranker_means_silence_and_the_judge_is_never_asked():
    asked = []

    def judge(prompt):
        asked.append(prompt)
        return 1.0

    outcome = agree("tool7 failed", "demo", LESSONS, judge)
    assert (outcome.verdict, outcome.note, asked) == (Verdict.RANKER_TOO_LOW, None, [])


def test_the_judge_is_asked_in_the_scored_layout_about_the_ranked_lesson():
    asked = []
    agree(QUESTION, "demo", LESSONS, lambda prompt: asked.append(prompt) or 1.0)
    expected = f"Situation:\n{QUESTION}\n\nLesson:\nIn demo, `tool7 module7` failed with Oops7;"
    assert asked[0].startswith(expected)


def test_a_judge_that_cannot_answer_raises_instead_of_reading_as_no():
    def down(prompt):
        raise ConnectionError("judge offline")

    with pytest.raises(ConnectionError):
        agree(QUESTION, "demo", LESSONS, down)


def test_no_lessons_is_its_own_verdict():
    assert agree(QUESTION, "demo", [], lambda prompt: 1.0).verdict is Verdict.NO_LESSONS
