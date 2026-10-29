"""Generation 0 cards: built cards obey the caps and differ; a Spark card naming a map raises."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import seed_cards  # noqa: E402 - needs the scripts path added above

from symbiont.act1.card_genome import MAX_LESSONS, MAX_WORDS, Card, Lesson  # noqa: E402
from symbiont.act1.generality import check_card  # noqa: E402
from symbiont.act1.lineage import Operator  # noqa: E402
from symbiont.act1.offline_author import AllowAllJudge, FlagWordJudge  # noqa: E402

pytestmark = pytest.mark.periphery


class CannedAuthor:
    """Returns the next canned card for each seed call and records what it was asked."""

    name = "canned"

    def __init__(self, cards):
        self.cards, self.asked = list(cards), []

    def vary(self, operator, parents, summary, seed):
        self.asked.append((operator, summary))
        return self.cards.pop(0)


def lesson(n):
    return Lesson(f"mistake {n}", f"habit {n}", f"check {n}?")


CANNED = [Card.of([lesson(n), lesson(n + 10)]) for n in (1, 2, 3)]


def test_the_two_built_cards_obey_the_caps_pass_the_filter_and_differ():
    first, second = seed_cards.built_cards()
    for card in (first, second):
        assert len(card.lessons) <= MAX_LESSONS and card.words() <= MAX_WORDS
        assert all(v.general for v in check_card(card))
    assert first.card_id != second.card_id and len(first.lessons) < len(second.lessons)


def test_six_distinct_cards_start_with_the_empty_card_and_three_come_from_the_author():
    author = CannedAuthor(CANNED)
    cards = seed_cards.build_seed_cards(author, AllowAllJudge())
    assert len(cards) == 6 and cards[0].lessons == ()
    assert [op for op, _ in author.asked] == [Operator.SEED_SPARK] * 3
    assert all("26 were moves that changed nothing" in text for _, text in author.asked)
    assert len({text for _, text in author.asked}) == 3  # three different focuses


def test_a_card_naming_a_map_raises_and_is_not_replaced():
    bad = Card.of([Lesson("Lost in MAP02", "Go back", "Is it MAP02?")])
    with pytest.raises(seed_cards.GeneralityRejectedError, match="map_name"):
        seed_cards.build_seed_cards(CannedAuthor([bad, *CANNED[1:]]), AllowAllJudge())


def test_a_card_the_judge_calls_a_landmark_raises():
    with pytest.raises(seed_cards.GeneralityRejectedError, match="landmark"):
        seed_cards.build_seed_cards(CannedAuthor(CANNED), FlagWordJudge("habit 2"))


def test_two_identical_seed_cards_raise():
    with pytest.raises(seed_cards.GeneralityRejectedError, match="identical"):
        seed_cards.build_seed_cards(CannedAuthor([CANNED[0]] * 3), AllowAllJudge())
