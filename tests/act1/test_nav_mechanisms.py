import math

import pytest

from nav_mech_world import START, TAG, lift, pedestal_key, switch_door, teleport
from symbiont.act1.map_index import build_index
from symbiont.act1.navmap import NoPath, Route, build_navmap
from symbiont.act1.navmech import apply_mechanism, build_mechanisms
from symbiont.act1.navspecials import UnknownSpecialError
from symbiont.act1.navtypes import Action, WorldNow
from symbiont.act1.wad import Thing


def nav_of(geometry):
    return build_navmap(geometry, build_index(geometry))


def way_to_exit(geometry, keys=()):
    nav = nav_of(geometry)
    return nav.path(START, nav.features("exit")[0], keys_held=keys, closed=frozenset())


def test_a_door_opened_by_a_switch_is_reached_by_pressing_the_switch_first():
    route = way_to_exit(switch_door())
    assert isinstance(route, Route)
    presses = [w for w in route.waypoints if w.action == Action.PRESS_SWITCH]
    assert len(presses) == 1
    assert presses[0].aim == (120.0, 256.0)  # the middle of the switch line
    assert math.dist((presses[0].x, presses[0].y), presses[0].aim) <= 64


def test_without_a_switch_the_same_door_is_a_wall_and_the_reason_is_given():
    result = way_to_exit(switch_door(switch=0))
    assert isinstance(result, NoPath)


def test_a_switch_that_closes_the_door_does_not_open_a_route():
    assert isinstance(way_to_exit(switch_door(switch=42)), NoPath)


def test_a_switch_that_needs_a_key_is_pressed_only_with_the_key():
    assert isinstance(way_to_exit(switch_door(switch=133)), NoPath)
    assert isinstance(way_to_exit(switch_door(switch=133), keys=("blue",)), Route)


def test_a_lift_called_by_a_switch_carries_the_walker_from_the_low_room_to_the_high_one():
    route = way_to_exit(lift())
    assert isinstance(route, Route)
    assert [w.action for w in route.waypoints].count(Action.PRESS_SWITCH) == 1


def test_a_lift_that_is_never_called_is_a_cliff():
    assert isinstance(way_to_exit(lift(switch=0)), NoPath)


def test_a_teleport_line_joins_two_rooms_the_walls_part():
    route = way_to_exit(teleport())
    assert isinstance(route, Route)
    crossing = [w for w in route.waypoints if w.lands_at is not None]
    assert len(crossing) == 1
    assert 192 < crossing[0].x < 224  # past the teleport line, on the pad
    assert crossing[0].lands_at == (500.0, 128.0)


def test_a_teleport_that_only_moves_monsters_is_not_a_way_across():
    assert isinstance(way_to_exit(teleport(special=126)), NoPath)


def test_a_linedef_special_nobody_listed_raises_rather_than_reading_as_a_wall():
    with pytest.raises(UnknownSpecialError, match="special 999"):
        nav_of(switch_door(switch=999))


def way_to_key(geometry):
    nav = nav_of(geometry)
    return nav.path(START, nav.features("key")[0], keys_held=(), closed=frozenset())


def test_a_card_on_a_pedestal_is_out_of_reach_from_the_floor_beside_it():
    assert isinstance(way_to_key(pedestal_key(switch=0)), NoPath)


def test_a_card_on_a_pedestal_is_reached_once_a_switch_has_lowered_the_pedestal():
    route = way_to_key(pedestal_key())
    assert isinstance(route, Route)
    assert [w.action for w in route.waypoints].count(Action.PRESS_SWITCH) == 1


def test_a_called_lift_in_the_engine_state_needs_no_second_press():
    geometry = lift()
    nav = nav_of(geometry)
    exit_ = nav.features("exit")[0]
    resting = [(s.floor, s.ceiling) for s in geometry.sectors]
    called = [(0, 192) if number == 1 else h for number, h in enumerate(resting)]
    for heights, presses in ((resting, 1), (called, 0)):
        found = nav.nearest_now(WorldNow(frozenset(), tuple(heights)), START, [exit_], ())
        assert not isinstance(found, NoPath)
        actions = [w.action for w in found[1].waypoints]
        assert actions.count(Action.PRESS_SWITCH) == presses


def test_a_barrel_in_a_doorway_is_part_of_the_wall():
    geometry = switch_door(switch=0)
    geometry.sectors[1] = geometry.sectors[1].__class__(0, 128, TAG)  # the doorway stands open
    assert isinstance(way_to_exit(geometry), Route)
    geometry.things.append(Thing(264, 128, 2035))
    assert isinstance(way_to_exit(geometry), NoPath)


def test_a_raised_floor_stops_at_its_own_ceiling_and_uses_the_neighbors_current_ceilings():
    geometry = pedestal_key(switch=140)  # S1 raise by 512: the pedestal's ceiling is 192
    nav = nav_of(geometry)
    (mech,) = [m for m in build_mechanisms(geometry) if m.number == 140]
    after = apply_mechanism(geometry, nav._grid.base_states, mech)
    assert after[1].floor_out == 192
    to_ceiling = [m for m in build_mechanisms(pedestal_key(switch=64)) if m.number == 64]
    lowered = list(nav._grid.base_states)
    lowered[0] = lowered[0].__class__(0, 0, 120)  # room A's ceiling now 120
    raised = apply_mechanism(geometry, lowered, to_ceiling[0])
    assert raised[1].floor_out == 120
