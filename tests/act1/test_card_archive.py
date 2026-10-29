"""Niche archive: best card per (length, focus), as ids and numbers only."""

import json

from symbiont.act1.card_archive import Archive, Focus, Length, focus_of, niche_of
from symbiont.act1.card_genome import Card, Lesson

DOOR = Lesson("Walked past a locked door", "Go to the door and open it", "Is the door open now?")
SHOT = Lesson(
    "Fired with no enemy in view", "Shoot only at an enemy you can see", "Is an enemy in view?"
)


def card_of(*lessons):
    return Card.of(lessons)


def test_a_three_lesson_door_card_lands_in_short_navigation():
    card = card_of(DOOR, DOOR, DOOR)
    archive = Archive()
    assert archive.offer(card, 0.3)
    assert list(archive.best) == [(Length.SHORT, Focus.NAVIGATION)]


def test_a_six_lesson_card_with_four_shooting_lessons_lands_in_long_combat():
    card = card_of(SHOT, SHOT, SHOT, SHOT, DOOR, DOOR)
    assert niche_of(card) == (Length.LONG, Focus.COMBAT)


def test_the_empty_card_is_short_navigation():
    assert niche_of(card_of()) == (Length.SHORT, Focus.NAVIGATION)


def test_half_combat_lessons_is_not_combat():
    assert focus_of(card_of(SHOT, DOOR)) == Focus.NAVIGATION


def test_a_better_card_replaces_and_a_worse_one_does_not():
    archive = Archive()
    first, better = card_of(DOOR), card_of(DOOR, DOOR)
    archive.offer(first, 0.2)
    assert archive.offer(better, 0.4)
    assert archive.best[(Length.SHORT, Focus.NAVIGATION)] == (better.card_id, 0.4)
    assert not archive.offer(first, 0.1)


def test_an_equal_but_longer_card_does_not_replace_and_a_shorter_one_does():
    archive = Archive()
    longer, shorter = card_of(DOOR, DOOR), card_of(DOOR)
    archive.offer(longer, 0.4)
    assert archive.offer(shorter, 0.4)
    assert archive.best[(Length.SHORT, Focus.NAVIGATION)][0] == shorter.card_id
    assert not archive.offer(longer, 0.4)


def test_to_json_holds_ids_and_numbers_but_no_lesson_text():
    archive = Archive()
    archive.offer(card_of(DOOR), 0.25)
    text = json.dumps(archive.to_json())
    assert "door" not in text.lower()
    assert card_of(DOOR).card_id in text
    assert "0.25" in text
