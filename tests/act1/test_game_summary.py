"""Game summaries tell an author what happened in prose: counts of games, never scores or places."""

import re

import pytest

from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.game_summary import NoGradedGamesError, summarize_games
from symbiont.act1.generality import check_text
from symbiont.act1.move_cuts import CutSetting


def game(index, exit_reached=False, share=0.0, died=False, grade=Grade.GRADED, mistakes=0):
    case = Case(f"MAP{index:02d}", 1000 + index, 3, CutSetting.NONE)
    reason = None if grade == Grade.GRADED else "SparkReplyError"
    return GameResult(
        case, "abc", grade, exit_reached, share, mistakes, died, 4, 1, reason
    )  # fmt: skip


MIXED = [
    game(1, exit_reached=True, share=1.0),
    game(2, share=0.3),
    game(3, share=0.2, died=True),
    game(5, share=0.0),
]
PAINS = {"wasted_move": 5, "room_rechecked": 9, "wall_bump": 1, "room_reentered": 0}


def test_the_summary_says_how_many_games_missed_the_exit_and_how_many_ended_in_death():
    text = summarize_games(MIXED, PAINS)
    assert "In 3 of 4 games the exit was not reached." in text
    assert "One game ended in death." in text


def test_the_most_common_mistake_is_named_in_words():
    assert "turns in rooms already checked" in summarize_games(MIXED, PAINS)


def test_route_share_is_a_coarse_word_for_the_games_that_missed_the_exit():
    assert "covered some of the route" in summarize_games(MIXED, PAINS)
    far = [game(1, share=0.9), game(2, share=0.8)]
    assert "covered most of the route" in summarize_games(far, PAINS)
    none = [game(1, share=0.0), game(2, share=0.01)]
    assert "covered none of the route" in summarize_games(none, PAINS)


def test_an_all_exit_fixture_says_so_and_has_no_route_sentence():
    wins = [game(1, exit_reached=True, share=1.0), game(2, exit_reached=True, share=1.0)]
    text = summarize_games(wins, {"wasted_move": 0})
    assert "In all 2 games the exit was reached." in text
    assert "route" not in text and "death" not in text


def test_no_tagged_mistake_is_said_plainly():
    assert "No mistakes were tagged." in summarize_games(MIXED, {"wasted_move": 0})


def test_the_summary_has_no_float_no_map_name_no_coordinate_and_passes_the_scan():
    text = summarize_games(MIXED, PAINS)
    assert not re.search(r"\d\.\d", text)
    assert not re.search(r"MAP\d", text)
    assert check_text(text).general


def test_ungraded_games_are_left_out_of_the_counts():
    games = [*MIXED, game(6, grade=Grade.UNGRADED)]
    assert "In 3 of 4 games" in summarize_games(games, PAINS)


def test_no_graded_game_raises():
    with pytest.raises(NoGradedGamesError):
        summarize_games([game(1, grade=Grade.UNGRADED)], PAINS)


def test_an_unknown_pain_name_raises_instead_of_being_ignored():
    with pytest.raises(ValueError, match="sneezing"):
        summarize_games(MIXED, {"sneezing": 2})
