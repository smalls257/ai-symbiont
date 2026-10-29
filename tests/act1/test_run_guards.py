"""Run guards: every stop raises or reports with the numbers that triggered it."""

import pytest

from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.generality import Rejection, Verdict
from symbiont.act1.move_cuts import CutSetting
from symbiont.act1.run_guards import (
    GapDecision,
    GapWatch,
    MutationPromptError,
    NoGamesError,
    NoiseVerdict,
    SpendRoom,
    TooManyUngradedError,
    noise_check,
    require_graded_share,
    require_rejection_share,
)

PLENTY = SpendRoom(remaining_usd=10.0, doubling_cost_usd=1.0)
SHORT = SpendRoom(remaining_usd=1.1, doubling_cost_usd=1.0)

# Seeds disagree by 1.0 on every level while the three card means are all 0.5.
SEEDS_DISAGREE = {name: ((0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0)) for name in "abc"}
# Seeds agree; the cards differ a lot.
CARDS_DIFFER = {
    "a": ((0.0, 0.0), (0.1, 0.1)),
    "b": ((0.5, 0.5), (0.6, 0.6)),
    "c": ((1.0, 1.0), (1.1, 1.1)),
}


def test_seed_noise_above_card_differences_doubles_the_games_when_money_allows():
    report = noise_check(SEEDS_DISAGREE, PLENTY, 8)
    assert report.verdict is NoiseVerdict.DOUBLE_GAMES
    assert report.within_variance == pytest.approx(0.5)
    assert report.between_variance == pytest.approx(0.0)


def test_noisy_games_do_not_hide_cards_that_truly_differ():
    # Single games disagree (within 0.5) but the 8-game card means sit 0.5 apart: the old
    # single-game comparison said noise; the like-for-like comparison selects.
    differ = {
        "a": ((0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0)),
        "b": ((0.5, 1.5), (1.5, 0.5), (0.5, 1.5), (1.5, 0.5)),
        "c": ((1.0, 2.0), (2.0, 1.0), (1.0, 2.0), (2.0, 1.0)),
    }
    report = noise_check(differ, SHORT, 8)
    assert report.verdict is NoiseVerdict.SELECT
    assert report.within_variance / 8 < report.between_variance


def test_seed_noise_with_too_little_money_left_stops_the_run():
    assert noise_check(SEEDS_DISAGREE, SHORT, 8).verdict is NoiseVerdict.STOP


def test_the_margin_is_twenty_percent_of_the_doubling_cost():
    just_enough = SpendRoom(remaining_usd=1.2, doubling_cost_usd=1.0)
    assert noise_check(SEEDS_DISAGREE, just_enough, 8).verdict is NoiseVerdict.DOUBLE_GAMES


def test_cards_that_differ_more_than_seeds_select():
    report = noise_check(CARDS_DIFFER, SHORT, 8)
    assert report.verdict is NoiseVerdict.SELECT
    assert report.within_variance == pytest.approx(0.0)
    assert report.between_variance > 0.0


def test_the_standard_error_of_a_four_game_mean_is_half_the_spread_of_all_games():
    report = noise_check(SEEDS_DISAGREE, PLENTY, 8)
    assert report.standard_error == pytest.approx(0.5 * (6 / 23) ** 0.5)


def watch(*gaps, threshold=0.1):
    guard = GapWatch(threshold)
    for generation, gap in enumerate(gaps, start=1):
        guard.record(generation, training_mean=1.0 + gap, validation_mean=1.0)
    return guard.verdict()


def test_two_rises_in_a_row_stop_with_the_generation_before_the_first_rise():
    verdict = watch(0.1, 0.3, 0.5)
    assert verdict.decision is GapDecision.STOP
    assert verdict.last_good_generation == 1
    assert "0.3" in verdict.detail and "0.5" in verdict.detail


def test_one_rise_then_a_small_one_continues():
    assert watch(0.1, 0.15, 0.3).decision is GapDecision.CONTINUE


def test_a_rise_exactly_at_the_threshold_is_not_a_rise():
    assert watch(0.0, 0.25, 0.5, threshold=0.25).decision is GapDecision.CONTINUE


def test_a_rise_then_a_fall_then_a_rise_continues():
    assert watch(0.1, 0.4, 0.1, 0.4).decision is GapDecision.CONTINUE


def result(index, grade):
    case = Case(f"MAP{index:02d}", index, 3, CutSetting.NONE)
    reason = None if grade == Grade.GRADED else "SparkReplyError"
    return GameResult(case, "abc", grade, False, 0.0, 0, False, 0, 0, reason)


def games(ungraded, total):
    return [result(i, Grade.UNGRADED if i < ungraded else Grade.GRADED) for i in range(total)]


def test_two_ungraded_of_twenty_passes_and_three_raises_naming_the_counts():
    require_graded_share(games(2, 20))
    with pytest.raises(TooManyUngradedError, match="3 of 20"):
        require_graded_share(games(3, 20))


def rejected(count, total):
    bad = Verdict(False, Rejection.MAP_NAME, "MAP02")
    good = Verdict(True, None, "")
    return [bad] * count + [good] * (total - count)


def test_two_rejections_of_four_passes_and_three_raises_naming_the_counts():
    require_rejection_share(rejected(2, 4))
    with pytest.raises(MutationPromptError, match="3 of 4"):
        require_rejection_share(rejected(3, 4))


def test_an_empty_list_of_games_raises_instead_of_passing():
    with pytest.raises(NoGamesError):
        require_graded_share([])


def test_the_same_data_is_noise_when_selection_averages_fewer_games_than_the_replay_did():
    # Luck in an 8-game mean is 0.0625, below the 0.25 spread of the cards: select. Selection that
    # averages only 1 game per card faces luck of 0.5, above the spread: noise.
    differ = {
        "a": ((0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0)),
        "b": ((0.5, 1.5), (1.5, 0.5), (0.5, 1.5), (1.5, 0.5)),
        "c": ((1.0, 2.0), (2.0, 1.0), (1.0, 2.0), (2.0, 1.0)),
    }
    assert noise_check(differ, PLENTY, 8).verdict is NoiseVerdict.SELECT
    assert noise_check(differ, PLENTY, 4).verdict is NoiseVerdict.SELECT
    assert noise_check(differ, PLENTY, 1).verdict is NoiseVerdict.DOUBLE_GAMES
    assert noise_check(differ, PLENTY, 2).verdict is NoiseVerdict.DOUBLE_GAMES


def test_the_report_says_how_many_games_per_card_selection_needs():
    report = noise_check(SEEDS_DISAGREE, PLENTY, 4)
    assert report.selection_games == 4 and report.games_per_mean == 8 and report.pairs_used == 12
    assert report.true_between_variance == 0.0 and report.games_needed is None  # cards identical
    differ = {
        "a": ((0.0, 1.0), (1.0, 0.0)),
        "b": ((0.5, 1.5), (1.5, 0.5)),
        "c": ((1.0, 2.0), (2.0, 1.0)),
    }
    report = noise_check(differ, PLENTY, 4)
    # within 0.5, between 0.25 over 4 games a mean: the spread beyond luck is 0.25 - 0.5/4
    assert report.true_between_variance == pytest.approx(0.125)
    assert report.games_needed == 4  # 0.5 / 0.125
