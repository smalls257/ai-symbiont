"""Move cuts: a seeded pure decision, so a replay cuts the same moves."""

import pytest

from symbiont.act1.move_cuts import (
    HARDER_SKILL,
    NORMAL_SKILL,
    CutSetting,
    MoveCuts,
    cuts_for,
)

MAX_TICS = 60


def test_ten_percent_cuts_about_a_tenth_of_ten_thousand_moves():
    cuts = MoveCuts(share=0.1, seed=7)
    cut = sum(cuts.tic_cap(n, MAX_TICS) is not None for n in range(10_000))
    assert 800 <= cut <= 1200  # [hypothesis] 8% to 12%; a seeded sample, so deterministic


def test_the_same_seed_cuts_the_same_moves_and_another_seed_does_not():
    one, again, other = MoveCuts(0.1, 3), MoveCuts(0.1, 3), MoveCuts(0.1, 4)
    caps = [one.tic_cap(n, MAX_TICS) for n in range(500)]
    assert caps == [again.tic_cap(n, MAX_TICS) for n in range(500)]
    assert caps != [other.tic_cap(n, MAX_TICS) for n in range(500)]


def test_a_cut_cap_is_between_one_tic_and_half_the_move():
    caps = [MoveCuts(1.0, 5).tic_cap(n, MAX_TICS) for n in range(300)]
    assert all(cap is not None and 1 <= cap <= MAX_TICS // 2 for cap in caps)


def test_a_one_tic_move_can_still_be_capped_without_an_empty_range():
    assert MoveCuts(1.0, 5).tic_cap(0, 1) == 1


def test_no_setting_gives_no_cuts_and_ten_percent_gives_a_tenth():
    assert cuts_for(CutSetting.NONE, 9) is None
    assert cuts_for(CutSetting.TEN_PERCENT, 9) == MoveCuts(share=0.1, seed=9)


def test_a_share_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="share"):
        MoveCuts(share=1.5, seed=1)


def test_the_skill_levels_are_normal_three_and_harder_four():
    assert (NORMAL_SKILL, HARDER_SKILL) == (3, 4)
