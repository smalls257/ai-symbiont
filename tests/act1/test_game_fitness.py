"""Fitness: exits dominate, standing still scores nothing, an ungraded game has no fitness."""

import pytest

from nav_world import START, trench_rooms, two_rooms, two_rooms_index
from symbiont.act1.game_fitness import (
    Case,
    GameResult,
    Grade,
    NoRouteError,
    UngradedGameError,
    fitness,
    remaining_route_units,
    route_share,
)
from symbiont.act1.map_index import build_index
from symbiont.act1.move_cuts import CutSetting
from symbiont.act1.navmap import build_navmap

CASE = Case("MAP01", 11, 3, CutSetting.NONE)


def result(**overrides):
    fields = {
        "case": CASE,
        "card_id": "abc",
        "grade": Grade.GRADED,
        "exit_reached": False,
        "route_share": 0.0,
        "mistakes": 0,
        "died": False,
        "kills": 0,
        "cut_moves": 0,
        "ungraded_reason": None,
    }
    return GameResult(**{**fields, **overrides})


def test_an_exit_scores_at_least_one_minus_its_penalties():
    won = result(exit_reached=True, route_share=1.0, mistakes=5)
    assert fitness(won) == pytest.approx(1.0 + 0.5 - 0.1)
    assert fitness(won) >= 1.0 - 0.02 * 5


def test_standing_at_the_start_with_no_mistakes_scores_zero():
    assert fitness(result()) == 0.0


def test_a_half_route_scores_a_quarter_point():
    assert fitness(result(route_share=0.5)) == pytest.approx(0.25)


def test_death_subtracts_half_a_point_and_kills_do_not_count():
    assert fitness(result(died=True)) == pytest.approx(-0.5)
    assert fitness(result(kills=9)) == fitness(result(kills=0))


def test_asking_for_the_fitness_of_an_ungraded_game_raises():
    broken = result(grade=Grade.UNGRADED, ungraded_reason="SparkReplyError")
    with pytest.raises(UngradedGameError, match="SparkReplyError"):
        fitness(broken)


def test_route_share_is_zero_at_the_start_half_way_and_clipped_at_one():
    assert route_share(start_units=400.0, remaining_units=400.0) == 0.0
    assert route_share(start_units=400.0, remaining_units=200.0) == 0.5
    assert route_share(start_units=400.0, remaining_units=0.0) == 1.0
    assert route_share(start_units=400.0, remaining_units=-20.0) == 1.0
    assert route_share(start_units=400.0, remaining_units=500.0) == 0.0


def test_a_start_with_no_walk_to_the_exit_raises():
    with pytest.raises(NoRouteError):
        route_share(start_units=0.0, remaining_units=0.0)


def two_room_nav(**kwargs):
    geometry = two_rooms(**kwargs)
    return build_navmap(geometry, two_rooms_index(geometry)[1])


def test_remaining_units_shrink_as_the_player_nears_the_exit():
    nav = two_room_nav()
    far, near = remaining_route_units(nav, START), remaining_route_units(nav, (400.0, 128.0))
    assert far > near > 0.0
    assert route_share(far, near) == pytest.approx(1.0 - near / far)


def test_a_locked_door_does_not_make_the_level_unroutable():
    nav = two_room_nav(door_special=26)
    assert remaining_route_units(nav, START) > 0.0


def test_an_unroutable_level_raises_naming_what_blocks():
    geometry = trench_rooms(width=64)
    nav = build_navmap(geometry, build_index(geometry))
    with pytest.raises(NoRouteError, match="exit"):
        remaining_route_units(nav, START)


def test_pains_default_to_empty_and_are_hashable_pairs():
    plain = result()
    assert plain.pains == ()
    tagged = result(pains=(("wasted_move", 2), ("wall_bump", 1)), mistakes=3)
    assert dict(tagged.pains) == {"wasted_move": 2, "wall_bump": 1}
    assert len({plain, tagged}) == 2
