"""Lesson card genome: caps are refused loudly, ids follow content, shorter cards win ties."""

import re

import pytest

from symbiont.act1.card_genome import (
    MAX_LESSONS,
    MAX_WORDS,
    Card,
    CardCapError,
    Lesson,
    LessonFormError,
)


def lesson(
    went_wrong="Turned in a room already checked",
    instead="Walk to the next door",
    check="Does the view show anything new?",
):
    return Lesson(went_wrong, instead, check, None)


def words_card(total_words):
    """A one-lesson card of exactly `total_words` filler words."""
    per_part = total_words // 3
    filler = " ".join(["word"] * per_part)
    extra = " ".join(["word"] * (total_words - 2 * per_part))
    return Card.of([Lesson(filler, filler, extra, None)])


def test_empty_card_renders_nothing_and_has_no_words():
    card = Card.of([])
    assert card.render() == ""
    assert card.words() == 0


def test_nine_lessons_raise_naming_the_count():
    with pytest.raises(CardCapError, match="9 lessons"):
        Card.of([lesson() for _ in range(MAX_LESSONS + 1)])


def test_eight_lessons_of_few_words_are_accepted():
    assert len(Card.of([lesson() for _ in range(MAX_LESSONS)]).lessons) == MAX_LESSONS


def test_251_words_raise_naming_the_count_and_250_pass():
    with pytest.raises(CardCapError, match="251 words"):
        words_card(MAX_WORDS + 1)
    assert words_card(MAX_WORDS).words() == MAX_WORDS


def test_an_empty_check_raises_a_form_error():
    with pytest.raises(LessonFormError, match="check"):
        Lesson("went wrong", "do instead", "   ", None)


def test_equal_content_gives_equal_ids_and_one_changed_word_a_different_id():
    one, same = Card.of([lesson()]), Card.of([lesson()])
    other = Card.of([lesson(instead="Walk to the next exit")])
    assert one.card_id == same.card_id
    assert one.card_id != other.card_id
    assert re.fullmatch(r"[0-9a-f]{12}", one.card_id)


def test_the_source_level_does_not_change_the_id():
    plain = Card.of([lesson()])
    sourced = Card.of([Lesson(*(lesson().went_wrong, lesson().instead, lesson().check), "MAP02")])
    assert plain.card_id == sourced.card_id


def test_tie_key_orders_a_short_card_before_a_longer_one():
    short, longer = words_card(40), words_card(60)
    assert short.tie_key() < longer.tie_key()
    assert short.tie_key()[0] == 40


def test_render_holds_no_digits_except_lesson_numbers():
    text = Card.of([lesson(), lesson(went_wrong="Fired with no enemy in view")]).render()
    assert not re.search(r"\d", re.sub(r"^\d+\. ", "", text, flags=re.M))
    assert text.splitlines()[1].startswith("2. ")


def test_a_card_survives_the_json_round_trip_with_its_source_levels():
    card = Card.of([Lesson("a", "b", "c", "MAP02"), lesson()])
    assert Card.from_json(card.to_json()) == card
    assert Card.from_json(card.to_json()).card_id == card.card_id


def test_a_stored_card_over_the_cap_still_raises_when_read_back():
    stored = [lesson().to_json() for _ in range(MAX_LESSONS + 1)]
    with pytest.raises(CardCapError):
        Card.from_json(stored)
