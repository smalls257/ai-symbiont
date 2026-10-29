"""The clip recorder takes the named seed, or the next one if a named game is ungraded."""

import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[2] / "scripts"
sys.path[:0] = [str(root / "act1"), str(root / "evolve")]

import frozen_cards as fc  # noqa: E402 - needs the scripts paths added above
import record_card_clips as rc  # noqa: E402
import run_state  # noqa: E402

from symbiont.act1.game_fitness import Case  # noqa: E402
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting  # noqa: E402

pytestmark = pytest.mark.periphery


def games_for(seed: int, grade: str) -> dict:
    case = Case("MAP04", seed, NORMAL_SKILL, CutSetting.NONE)
    return {run_state.game_key(card.card_id, case): {"grade": grade} for card in fc.ARMS.values()}


def test_named_seed_is_used_when_every_arm_is_graded():
    assert rc.choose_seed(games_for(2001, "graded"), "MAP04", 2001) == (2001, False)


def test_next_seed_replaces_an_ungraded_named_game():
    games = {**games_for(2001, "ungraded"), **games_for(2002, "graded")}
    assert rc.choose_seed(games, "MAP04", 2001) == (2002, True)


def test_two_ungraded_seeds_raise_instead_of_picking_a_third():
    games = {**games_for(2001, "ungraded"), **games_for(2002, "ungraded")}
    with pytest.raises(rc.NoGradedClipError):
        rc.choose_seed(games, "MAP04", 2001)
