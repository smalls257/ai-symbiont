"""The night's rows follow the round-4 recipe: balanced yes and no, 25% general replay, 15% habits.

Violation prevented: Infected Core. The recipe is arithmetic over lists, so these tests need no
model, no disk and no network.
"""

import re

import pytest

from nightly_support import PROJECT, failed_command_lesson, general_rows, habit_rows
from symbiont.core.judge_format import JUDGE_SYSTEM
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.service.nightly_rows import (
    HABIT_SHARE,
    PHRASINGS,
    PHRASINGS_PER_LESSON,
    REPLAY_SHARE,
    NoUsableLessonsError,
    night_rows,
    trainable_lessons,
    with_habits,
    with_replay,
)


def trainable(count):
    return trainable_lessons([failed_command_lesson(i) for i in range(count)], PROJECT)


def answers(rows, system):
    return [r["messages"][2]["content"] for r in rows if r["messages"][0]["content"] == system]


def test_a_lesson_without_a_fix_command_is_left_out_and_none_usable_raises():
    pain = PainPoint(Signature(Signal.CORRECTION, ("x",)), "s", 1, (("s", 1),))
    unfit = Lesson(pain, "you said no", (), "no fix", True, pain.record_refs)
    kept = trainable_lessons([failed_command_lesson(1), unfit], PROJECT)
    assert len(kept) == 1
    with pytest.raises(NoUsableLessonsError, match="none of the 1 lessons"):
        trainable_lessons([unfit], PROJECT)


def test_the_lessons_file_comes_from_the_lesson_and_defaults_to_the_round_3_dash():
    (with_file,) = trainable_lessons([failed_command_lesson(1, files=("a/b.py",))], PROJECT)
    (without,) = trainable_lessons([failed_command_lesson(1, files=())], PROJECT)
    assert "(file a/b.py)" in with_file.situation()
    assert "(file -)" in without.situation()


def test_own_rows_are_balanced_and_each_lesson_is_asked_in_several_situations():
    rows = night_rows(trainable(8), general_rows(), habit_rows())
    own = [
        r
        for r in rows
        if r["messages"][0]["content"] == JUDGE_SYSTEM and "demo" in r["messages"][1]["content"]
    ]
    answered = answers(own, JUDGE_SYSTEM)
    assert answered.count("yes") == answered.count("no") == 8 * (1 + PHRASINGS_PER_LESSON)


def numbers_in(text):
    return set(re.findall(r"test_(\d+)\.py", text))


def test_yes_rows_pair_a_situation_with_its_own_lesson_and_no_rows_with_another():
    rows = night_rows(trainable(8), general_rows(), habit_rows())
    own = [r for r in rows if "In demo," in r["messages"][1]["content"]]
    assert own
    for row in own:
        situation, lesson = row["messages"][1]["content"].split("\n\nLesson:\n")
        same = numbers_in(situation) == numbers_in(lesson.split("\n\n")[0])
        assert same == (row["messages"][2]["content"] == "yes")


def test_a_repository_with_one_lesson_gets_negatives_from_the_general_rows_not_nothing():
    rows = night_rows(trainable(1), general_rows(), habit_rows())
    own = [
        r
        for r in rows
        if "In demo," in r["messages"][1]["content"] or "demo" in r["messages"][1]["content"]
    ]
    answered = answers(own, JUDGE_SYSTEM)
    assert answered.count("no") == answered.count("yes") > 0


def test_general_rows_make_up_a_quarter_and_habits_fifteen_percent():
    rows = night_rows(trainable(10), general_rows(200), habit_rows(10))
    habit_count = sum(1 for r in rows if r["messages"][0]["content"] == "habit")
    assert habit_count / len(rows) == pytest.approx(HABIT_SHARE, abs=0.01)
    judge = [r for r in rows if r["messages"][0]["content"] == JUDGE_SYSTEM]
    general = [r for r in judge if "foo" in r["messages"][1]["content"]]
    assert len(general) / (len(rows) - habit_count) == pytest.approx(REPLAY_SHARE, abs=0.02)


def test_the_same_inputs_give_the_same_rows():
    first = night_rows(trainable(6), general_rows(), habit_rows())
    assert first == night_rows(trainable(6), general_rows(), habit_rows())


def test_replay_never_asks_for_more_general_rows_than_exist():
    assert len(with_replay([{"m": 1}] * 100, [{"m": 2}] * 3, REPLAY_SHARE)) == 103


def test_habit_replay_samples_with_replacement_up_to_the_share():
    mixed = with_habits([{"a": 1}] * 85, [{"h": 1}], 0)
    assert len(mixed) == 100


def test_fourteen_fixed_phrasings_are_all_formattable():
    (item,) = trainable(1)
    assert all(item.reworded(template) for template in PHRASINGS)
