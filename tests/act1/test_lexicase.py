"""Lexicase selection: specialists survive, dominated cards do not, ungraded cases are dropped."""

import random
from collections import Counter

import pytest

from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.lexicase import (
    FitnessTable,
    IncompleteTableError,
    NoGradableCaseError,
    elites,
    random_parents,
    select_parents,
)
from symbiont.act1.move_cuts import CutSetting

LEVELS = ("MAP01", "MAP02", "MAP03")


def case(level):
    return Case(level, 1, 3, CutSetting.NONE)


def game(card, level, share, grade=Grade.GRADED):
    """A game whose fitness is half of `share`."""
    return GameResult(
        case(level), card, grade, False, share, 0, False, 0, 0,
        None if grade == Grade.GRADED else "SparkReplyError",
    )  # fmt: skip


def table_of(scores):
    """scores: card -> one share per level in LEVELS."""
    results = [
        game(card, lv, s) for card, row in scores.items() for lv, s in zip(LEVELS, row, strict=True)
    ]
    return FitnessTable.of(results)


def by_id(card):
    return (len(card), card)


SPECIALISTS = {"a": (1.0, 0.0, 0.0), "b": (0.0, 1.0, 0.0), "c": (0.0, 0.0, 1.0)}


def test_a_card_best_on_one_case_only_is_selected_sometimes():
    table = table_of({**SPECIALISTS, "mean": (0.4, 0.4, 0.4)})
    rng = random.Random(0)
    picked = Counter(select_parents(table, 1, rng, by_id)[0] for _ in range(1000))
    assert picked["a"] > 0 and picked["b"] > 0 and picked["c"] > 0


def test_a_dominated_card_is_never_selected():
    table = table_of({**SPECIALISTS, "worse": (0.0, 0.0, 0.0)})
    rng = random.Random(1)
    assert "worse" not in {select_parents(table, 1, rng, by_id)[0] for _ in range(1000)}


def test_the_same_rng_seed_gives_the_same_parents():
    table = table_of({**SPECIALISTS, "mean": (0.4, 0.4, 0.4)})
    first = select_parents(table, 8, random.Random(5), by_id)
    assert first == select_parents(table, 8, random.Random(5), by_id)
    assert len(first) == 8


def test_survivors_of_every_case_are_broken_by_the_tie_key_shorter_first():
    table = table_of({"long-card": (0.5, 0.5, 0.5), "x": (0.5, 0.5, 0.5)})
    assert set(select_parents(table, 20, random.Random(2), by_id)) == {"x"}


def test_elites_are_the_best_by_mean_and_the_shorter_card_wins_a_tie():
    table = table_of({"best": (1.0, 1.0, 1.0), "mid": (0.5, 0.5, 0.5), "long-mid": (0.5, 0.5, 0.5)})
    assert elites(table, 2, by_id) == ("best", "mid")


def test_a_case_with_one_ungraded_game_is_dropped_for_all_cards_and_listed():
    results = [game(c, lv, 0.5) for c in ("a", "b") for lv in LEVELS]
    results[1] = game("a", "MAP02", 0.0, Grade.UNGRADED)
    table = FitnessTable.of(results)
    assert table.dropped_cases == (case("MAP02"),)
    assert table.cases == (case("MAP01"), case("MAP03"))
    assert ("b", case("MAP02")) not in table.scores


def test_a_table_with_no_gradable_case_raises():
    results = [game(c, "MAP01", 0.0, Grade.UNGRADED) for c in ("a", "b")]
    with pytest.raises(NoGradableCaseError, match="1 case"):
        FitnessTable.of(results)


def test_two_games_on_one_case_are_averaged():
    table = FitnessTable.of([game("a", "MAP01", 0.2), game("a", "MAP01", 0.6)])
    assert table.scores[("a", case("MAP01"))] == pytest.approx(0.2)


def test_random_parents_ignore_fitness_and_follow_the_seed():
    cards = ("a", "b", "c", "d")
    drawn = random_parents(cards, 200, random.Random(3))
    assert set(drawn) == set(cards)
    assert drawn == random_parents(cards, 200, random.Random(3))


def test_a_card_missing_a_game_on_a_kept_case_raises_rather_than_scoring_a_default():
    results = [game("a", "MAP01", 0.5), game("a", "MAP02", 0.5), game("b", "MAP01", 0.5)]
    with pytest.raises(IncompleteTableError, match="b"):
        FitnessTable.of(results)


def test_equally_short_survivors_are_chosen_by_chance_not_by_id():
    table = table_of({"aa": (0.5, 0.5, 0.5), "bb": (0.5, 0.5, 0.5), "long-card": (0.5, 0.5, 0.5)})
    rng = random.Random(9)
    picked = Counter(select_parents(table, 1, rng, by_id)[0] for _ in range(200))
    assert set(picked) == {"aa", "bb"} and min(picked.values()) > 50
