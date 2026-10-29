"""Generality filter: each pattern has a positive and a near miss; a rejection names its reason."""

import pytest

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.generality import Rejection, Verdict, check_card, check_lesson


def lesson(went_wrong="Wandered", instead="Walk to the next door", check="Did the view change?"):
    return Lesson(went_wrong, instead, check, None)


@pytest.mark.parametrize(
    ("text", "rejection"),
    [
        ("In MAP07 the walk stalled", Rejection.MAP_NAME),
        ("On E1M3 the key was missed", Rejection.MAP_NAME),
        ("Standing at x=512 shooting nothing", Rejection.COORDINATE),
        ("The walk ended at (1024, -256) every time", Rejection.COORDINATE),
        ("It was stuck at 12,34 again", Rejection.COORDINATE),
        ("Sector 12 is a dead end", Rejection.SECTOR),
        ("Open door 3 first", Rejection.DOOR_NUMBER),
        ("Go through the 2nd door", Rejection.DOOR_NUMBER),
        ("Take the third door on the left", Rejection.DOOR_NUMBER),
        ("The imp behind the crate keeps firing", Rejection.MONSTER_POSITION),
        ("A Zombieman at the stairs was ignored", Rejection.MONSTER_POSITION),
    ],
)
def test_each_pattern_rejects_its_positive_and_names_the_reason(text, rejection):
    verdict = check_lesson(lesson(went_wrong=text))
    assert verdict.general is False
    assert verdict.rejection is rejection
    assert verdict.evidence != ""


@pytest.mark.parametrize(
    "text",
    [
        "Read the map before walking",
        "Turn 90 degrees, then 180 if nothing is in view",
        "Fire only when 2 enemies are close",
        "Open a locked door only with its key",
        "Shoot the nearest imp",
        "An imp was shot and the walk went on",
        "Walked into the wall 3 times in the start room, heading north",
        "Head for the sector you have not turned in",
    ],
)
def test_each_near_miss_is_accepted(text):
    verdict = check_lesson(lesson(instead=text))
    assert verdict == Verdict(general=True, rejection=None, evidence="")


def test_the_check_part_is_scanned_too():
    assert check_lesson(lesson(check="Is this MAP12?")).rejection is Rejection.MAP_NAME


def test_check_card_gives_one_verdict_per_lesson_in_order():
    card = Card.of([lesson(), lesson(went_wrong="Stuck in MAP03")])
    verdicts = check_card(card)
    assert [v.general for v in verdicts] == [True, False]


def test_history_style_lessons_pass_and_a_named_map_fails():
    history = [
        lesson("`walk_to(exit)` walked into a wall 3 times in the start room, heading north."),
        lesson("`turn(90)` was repeated 4 times in the second room with nothing new in view."),
        lesson("`shoot_nearest()` fired with no enemy in view twice."),
    ]
    assert all(v.general for v in check_card(Card.of(history)))
    assert not check_lesson(lesson("It happened in MAP02 again")).general
