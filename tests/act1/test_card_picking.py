"""Picking: one rule for both arms, validation never used, a lesson must earn its place."""

import random

import pytest

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.card_picking import (
    GameRole,
    NoSharedCaseError,
    NotEnoughLevelsError,
    PlayedGame,
    ValidationUsedForPickingError,
    cross_level_cases,
    keep_lessons,
    pick_best,
)
from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.move_cuts import CutSetting


def case(level, seed=1):
    return Case(level, seed, 3, CutSetting.NONE)


def game(card, level, share, seed=1, grade=Grade.GRADED):
    reason = None if grade == Grade.GRADED else "SparkReplyError"
    return GameResult(case(level, seed), card, grade, False, share, 0, False, 0, 0, reason)


def played(card, generation, share, level="MAP01", role=GameRole.SELECTION, seed=1):
    return PlayedGame(game(card, level, share, seed), generation, role)


def by_id(card):
    return (len(card), card)


def test_a_card_with_one_high_game_loses_to_a_steadier_card():
    games = [
        played("lucky", 3, 1.0), played("lucky", 3, 0.0, "MAP02"),
        played("lucky", 4, 0.0, "MAP03"), played("steady", 3, 0.4),
        played("steady", 3, 0.4, "MAP02"), played("steady", 4, 0.4, "MAP03"),
    ]  # fmt: skip
    assert pick_best(games, (3, 4), by_id) == "steady"


def test_equal_means_pick_the_shorter_card():
    games = [played("long-card", 3, 0.5), played("x", 3, 0.5)]
    assert pick_best(games, (3, 4), by_id) == "x"


def test_only_the_last_two_generations_count_and_ungraded_games_are_left_out():
    games = [
        played("a", 1, 1.0), played("a", 3, 0.2), played("b", 3, 0.3),
        PlayedGame(game("a", "MAP04", 0.0, grade=Grade.UNGRADED), 3, GameRole.SELECTION),
    ]  # fmt: skip
    assert pick_best(games, (3, 4), by_id) == "b"


def test_a_validation_result_raises_even_outside_the_picked_generations():
    games = [played("a", 3, 0.5), played("a", 1, 0.9, "MAP07", GameRole.VALIDATION)]
    with pytest.raises(ValidationUsedForPickingError, match="MAP07"):
        pick_best(games, (3, 4), by_id)


def sourced(*levels):
    return Card.of([Lesson("went wrong", "do instead", "the check", level) for level in levels])


POOL = tuple(f"MAP{n:02d}" for n in (1, 2, 3, 5, 6, 9))


def test_cross_level_cases_never_use_a_lessons_source_level():
    card = sourced("MAP01", "MAP02", None)
    for seed in range(50):
        cases = cross_level_cases(card, POOL, random.Random(seed))
        assert len(cases) == 2
        assert {c.level for c in cases}.isdisjoint({"MAP01", "MAP02"})
        assert len({c.level for c in cases}) == 2


def test_cross_level_cases_follow_the_rng_seed():
    card = sourced("MAP01")
    assert cross_level_cases(card, POOL, random.Random(4)) == cross_level_cases(
        card, POOL, random.Random(4)
    )


def test_too_few_eligible_levels_raise_rather_than_reuse_a_source_level():
    card = sourced("MAP01", "MAP02", "MAP03", "MAP05")
    with pytest.raises(NotEnoughLevelsError, match="2 eligible"):
        cross_level_cases(card, POOL, random.Random(0), count=3)


def shares(card_id, *values):
    return [game(card_id, f"MAP{n:02d}", v) for n, v in enumerate(values, start=10)]


def test_a_lesson_whose_removal_raises_the_mean_is_cut_and_an_equal_one_stays():
    card = sourced("MAP01", "MAP02", "MAP03")
    with_card = shares("full", 0.4, 0.4)
    without = {
        0: shares("no0", 0.6, 0.6),  # better without lesson 0: cut
        1: shares("no1", 0.4, 0.4),  # equal: stays
        2: shares("no2", 0.2, 0.2),  # worse without: stays
    }
    kept = keep_lessons(card, with_card, without)
    assert kept.lessons == card.lessons[1:]


def test_cutting_every_lesson_gives_the_empty_card():
    card = sourced("MAP01", "MAP02")
    without = {0: shares("a", 0.9, 0.9), 1: shares("b", 0.9, 0.9)}
    kept = keep_lessons(card, shares("full", 0.1, 0.1), without)
    assert kept.lessons == () and kept.render() == ""


def test_only_the_shared_graded_cases_are_compared():
    card = sourced("MAP01")
    with_card = shares("full", 0.5, 0.0, 0.5)
    ablated = shares("no0", 0.5, 0.9, 0.5)
    ablated[1] = game("no0", "MAP11", 0.9, grade=Grade.UNGRADED)
    assert keep_lessons(card, with_card, {0: ablated}).lessons == card.lessons


def test_a_missing_ablation_raises():
    with pytest.raises(ValueError, match="lesson 1"):
        keep_lessons(sourced("MAP01", "MAP02"), shares("full", 0.1), {0: shares("a", 0.1)})


def test_an_ablation_sharing_no_graded_case_raises_instead_of_keeping_the_lesson():
    ablated = [game("no0", "MAP30", 0.5)]
    with pytest.raises(NoSharedCaseError):
        keep_lessons(sourced("MAP01"), shares("full", 0.5), {0: ablated})
