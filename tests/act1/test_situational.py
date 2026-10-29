"""Situational lessons: the ranker matches situations, the cutoff keeps most moves silent."""

import pytest

from symbiont.act1.situational import (
    HEADING,
    NoLessonsError,
    Ranker,
    SituationalLesson,
    cutoff_for_show_rate,
    render_lessons,
)

IMP_ROOM = "Player: health 40. Visible: DoomImp (enemy) 200 units, straight ahead. Layout: walls"
KEY_ROOM = "Player: health 100. Reachable with go_to: YellowCard 900 units by path; door 40 units"
FIGHT = SituationalLesson("Back off from the imp before shooting", (IMP_ROOM,))
DOOR = SituationalLesson("Fetch the yellow key before the door", (KEY_ROOM,))


def test_the_lesson_whose_example_matches_the_moment_scores_highest():
    ranker = Ranker([FIGHT, DOOR])
    fight_score, door_score = ranker.scores("Visible: DoomImp (enemy) 90 units, straight ahead")
    assert fight_score > door_score


def test_numbers_do_not_change_a_score():
    ranker = Ranker([FIGHT])
    assert ranker.scores("DoomImp enemy 10 units") == ranker.scores("DoomImp enemy 999 units")


def test_below_the_cutoff_nothing_is_chosen():
    ranker = Ranker([FIGHT, DOOR])
    assert ranker.choose("Layout: open space ahead", cutoff=0.5) == []


def test_at_most_two_lessons_are_chosen_best_first():
    third = SituationalLesson("Stay near cover", (IMP_ROOM + " cover",))
    ranker = Ranker([DOOR, FIGHT, third])
    chosen = ranker.choose(IMP_ROOM, cutoff=0.0)
    assert len(chosen) == 2 and chosen[0] == FIGHT.advice


def test_a_lesson_with_no_example_cannot_be_ranked():
    with pytest.raises(NoLessonsError):
        Ranker([SituationalLesson("advice", ())])
    with pytest.raises(NoLessonsError):
        Ranker([])


def test_rendering_says_use_one_only_if_it_applies_and_is_empty_when_silent():
    assert render_lessons([]) == ""
    text = render_lessons(["Do this"])
    assert text.startswith(HEADING) and "use one only if it applies" in text and "- Do this" in text


def test_the_cutoff_for_a_show_rate_shows_about_that_share():
    scores = [i / 100 for i in range(100)]
    cutoff = cutoff_for_show_rate(scores, 0.25)
    assert sum(s >= cutoff for s in scores) == 25
    with pytest.raises(ValueError):
        cutoff_for_show_rate(scores, 1.5)
