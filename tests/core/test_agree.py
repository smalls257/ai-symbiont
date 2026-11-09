"""The agree rule: both the ranker and the judge must clear their frozen bars, else silence.

Hand-written lessons, no network: the judge is a function. The failures guarded against are a
Paper Tiger (a best guess shown whatever its score) and a Silent Fallback (a judge that cannot
answer read as "no").
"""

import math

import pytest

from symbiont.core.agree import (
    AGREE,
    JUDGE_MIN_P_YES,
    RANKER_MIN_SCORE,
    Verdict,
    agree,
    attainable_ceiling,
    ranker_cut,
    ranker_scores,
)
from symbiont.core.notes import render_lesson
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature


def lesson(index, fix="ran `pip install pyyaml`"):
    signature = Signature(Signal.FAILED_COMMAND, (f"tool{index}", f"module{index}", f"Oops{index}"))
    pain = PainPoint(signature, "s1", index, (("s1", index),))
    return Lesson(
        pain,
        f"$ tool{index} module{index}\nOops{index}",
        (fix,),
        None,
        True,
        (("s1", 1),),
        fix_commands=("pip install pyyaml",),
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

    outcome = agree("pytest failed again", "demo", LESSONS, judge)
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


SMALL = LESSONS[:4]


def test_the_cut_is_the_round_4_share_of_this_stores_ceiling():
    ceiling = attainable_ceiling(SMALL)
    assert ranker_cut(SMALL, AGREE) == pytest.approx(10.0 / 43.0 * ceiling)
    assert ranker_cut(SMALL, AGREE) < 10.0 / 2  # frozen 10.0 is out of reach for four lessons


def test_a_small_store_fires_on_an_exact_repeat():
    asked = []
    repeat = "tool2 module2 failed with Oops2 again"
    outcome = agree(repeat, "demo", SMALL, lambda prompt: asked.append(prompt) or 1.0)
    assert outcome.verdict is Verdict.AGREED and outcome.note == render_lesson(SMALL[2])
    assert outcome.ranker_score < RANKER_MIN_SCORE  # the unscaled cut would have silenced it


def test_an_unrelated_failure_stays_silent_on_a_small_store_and_the_log_numbers_say_why():
    outcome = agree("npm run build crashed", "demo", SMALL, lambda prompt: 1.0)
    assert outcome.verdict is Verdict.RANKER_TOO_LOW and outcome.note is None
    assert outcome.ranker_cut > 0 and outcome.ranker_score < outcome.ranker_cut


def test_a_store_of_one_lesson_has_no_ceiling_and_says_so_instead_of_firing_on_anything():
    outcome = agree("npm run build crashed", "demo", SMALL[:1], lambda prompt: 1.0)
    assert (outcome.verdict, outcome.ceiling) == (Verdict.RANKER_TOO_LOW, 0.0)


def test_the_cut_equals_the_harness_value_for_a_fixed_store():
    # Four lessons, three words each, every word in one lesson only: ceiling = 3 * ln(4), and the
    # plug harness (f27b334 `ranker_cut`: 10.0 / 43.0 * ceiling) computes the same by that formula.
    expected = 10.0 / 43.0 * 3 * math.log(4)
    assert ranker_cut(SMALL, AGREE) == pytest.approx(expected, abs=1e-9)
    assert expected == pytest.approx(0.96719, abs=1e-5)
