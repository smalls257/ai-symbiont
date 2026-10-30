import math

from nav_world import (
    DOOR,
    EXIT_MID,
    START,
    ledge_room,
    trench_rooms,
    two_rooms,
    two_rooms_index,
)
from symbiont.act1.map_index import MapIndex, build_index
from symbiont.act1.navmap import Feature, NoPath, Route, build_navmap


def navmap(**kwargs):
    geometry = two_rooms(**kwargs)
    return build_navmap(geometry, two_rooms_index(geometry)[1])


def exit_feature(nav):
    return nav.features("exit")[0]


def test_path_to_the_exit_goes_through_the_door_and_says_which_one():
    nav = navmap()
    route = nav.path(START, exit_feature(nav), keys_held=())
    assert isinstance(route, Route)
    assert route.doors == 1
    assert [w.door_sector for w in route.waypoints if w.door_sector is not None] == [DOOR]
    assert (
        route.length >= math.dist(START, EXIT_MID) - 40
    )  # the route ends within the exit's reach, not on it
    assert math.dist((route.waypoints[-1].x, route.waypoints[-1].y), EXIT_MID) <= 40


def test_door_waypoint_is_on_the_near_side_so_the_door_is_opened_before_walking_in():
    nav = navmap()
    route = nav.path(START, exit_feature(nav), keys_held=())
    door_waypoint = next(w for w in route.waypoints if w.door_sector is not None)
    assert door_waypoint.x < 256  # still in room A


def test_locked_door_without_the_key_is_no_path_naming_the_colour():
    nav = navmap(door_special=26)
    result = nav.path(START, exit_feature(nav), keys_held=())
    assert isinstance(result, NoPath)
    assert "blue" in result.reason and "locked" in result.reason


def test_locked_door_with_the_key_is_a_path():
    nav = navmap(door_special=26)
    assert isinstance(nav.path(START, exit_feature(nav), keys_held=("blue",)), Route)


def test_key_object_names_count_as_holding_the_colour():
    nav = navmap(door_special=26)
    assert isinstance(nav.path(START, exit_feature(nav), keys_held=("BlueCard",)), Route)
    assert isinstance(nav.path(START, exit_feature(nav), keys_held=("RedCard",)), NoPath)


def test_a_solid_wall_between_the_rooms_is_no_route_not_a_fake_path():
    nav = navmap(door_special=None)
    result = nav.path(START, exit_feature(nav), keys_held=())
    assert isinstance(result, NoPath)
    assert "no route" in result.reason


def test_impassable_flag_makes_a_two_sided_line_a_wall_and_without_it_the_line_is_open():
    assert isinstance(
        navmap(door_special=None, window_flags=0).path(START, exit_feature(navmap()), ()), Route
    )
    blocked = navmap(door_special=None, window_flags=1)
    assert isinstance(blocked.path(START, exit_feature(blocked), ()), NoPath)


def test_a_floor_step_taller_than_the_player_can_climb_is_a_wall():
    nav = navmap(door_special=None, window_flags=0)  # open line between A and B ...
    geometry = two_rooms(
        door_special=None, window_flags=0, sector_heights=[(0, 128), (0, 0), (40, 168)]
    )
    stepped = build_navmap(
        geometry, two_rooms_index(geometry)[1]
    )  # ... but room B's floor is 40 higher
    assert isinstance(nav.path(START, exit_feature(nav), ()), Route)
    assert isinstance(stepped.path(START, exit_feature(stepped), ()), NoPath)


def test_a_door_can_be_walked_to_without_going_through_it():
    nav = navmap()
    door = nav.features("door")[0]
    route = nav.path(START, door, keys_held=())
    assert isinstance(route, Route) and route.doors == 0
    assert route.waypoints[-1].x < 256


def test_a_route_to_a_point_in_the_same_room_has_no_doors():
    nav = navmap()
    route = nav.path(START, (200.0, 200.0), keys_held=())
    assert isinstance(route, Route) and route.doors == 0
    assert math.dist((route.waypoints[-1].x, route.waypoints[-1].y), (200, 200)) <= 24


def test_a_point_inside_a_wall_is_no_path_saying_it_is_not_walkable():
    result = navmap().path(START, (1000.0, 1000.0), keys_held=())
    assert isinstance(result, NoPath) and "walkable" in result.reason


def test_nearest_skips_a_target_that_is_close_in_a_straight_line_but_walled_off():
    nav = navmap(door_special=None)
    card = nav.features("key")[0]
    behind_the_wall = Feature(kind="object", label="Stimpack", x=300.0, y=128.0)
    found = nav.nearest((240.0, 128.0), [behind_the_wall, card], keys_held=())
    assert found[0] is card and isinstance(found[1], Route)


def test_nearest_measures_by_path_length_through_the_door():
    nav = navmap()
    card = nav.features("key")[0]
    behind_the_door = Feature(kind="object", label="Stimpack", x=300.0, y=128.0)
    found = nav.nearest((240.0, 128.0), [behind_the_door, card], keys_held=())
    assert found[0] is behind_the_door
    assert found[1].doors == 1


def test_nearest_reports_every_blocker_when_nothing_is_reachable():
    nav = navmap(door_special=26)
    result = nav.nearest(START, [exit_feature(nav)], keys_held=())
    assert isinstance(result, NoPath) and "blue" in result.reason


def test_start_inside_a_wall_is_no_path_with_that_reason():
    result = navmap().path((-500.0, -500.0), exit_feature(navmap()), keys_held=())
    assert isinstance(result, NoPath) and "start" in result.reason


def test_features_list_doors_exits_and_keys_from_the_index():
    nav = navmap()
    assert [f.kind for f in nav.features("door")] == ["door"]
    assert nav.features("door")[0].door_sector == DOOR
    assert isinstance(nav.features("exit")[0], Feature)
    assert nav.features("key")[0].key_colour == "blue"


def trench_nav(width):
    geometry = trench_rooms(width)
    return build_navmap(geometry, build_index(geometry))


def test_a_player_straddles_a_narrow_trench_between_two_rooms():
    nav = trench_nav(8)
    assert isinstance(nav.path(START, nav.features("exit")[0], ()), Route)


def test_a_wide_deep_trench_is_no_route_and_the_reason_names_the_climb():
    nav = trench_nav(96)
    result = nav.path(START, nav.features("exit")[0], ())
    assert isinstance(result, NoPath)
    assert "400-unit climb" in result.reason and "nearest reachable point" in result.reason


def test_dropping_down_a_ledge_is_allowed_but_climbing_back_up_is_not():
    geometry = two_rooms(
        door_special=None, window_flags=0, sector_heights=[(0, 128), (0, 0), (40, 168)]
    )
    nav = build_navmap(geometry, two_rooms_index(geometry)[1])
    assert isinstance(
        nav.path((400.0, 128.0), (100.0, 100.0), ()), Route
    )  # B is 40 higher: step down
    assert isinstance(nav.path((100.0, 100.0), (400.0, 128.0), ()), NoPath)  # and 40 up is too much


def test_an_unlisted_closed_door_reads_as_a_wall_naming_the_headroom():
    geometry = two_rooms(door_special=1)
    index = build_index(geometry)
    no_doors = MapIndex(
        (), index.exits, index.keys, index.sectors
    )  # the door line is not known as a door
    nav = build_navmap(geometry, no_doors)
    result = nav.path(START, nav.features("exit")[0], ())
    assert isinstance(result, NoPath) and "headroom" in result.reason


def test_a_route_goes_round_a_ledge_instead_of_cutting_straight_over_it():
    geometry = ledge_room()
    nav = build_navmap(geometry, build_index(geometry))
    route = nav.path((64.0, 128.0), (450.0, 128.0), ())
    assert isinstance(route, Route)
    assert max(w.y for w in route.waypoints) > 200  # up round the top of the ledge
    assert route.length > 450 - 64 + 40  # clearly longer than the straight line over it


def one_face_nav(faces):
    geometry = two_rooms(faces=faces)
    return build_navmap(geometry, two_rooms_index(geometry)[1])


def test_a_door_whose_use_face_is_on_the_far_side_cannot_be_opened_from_here():
    nav = one_face_nav("b")  # only room B's face carries the special; the player starts in room A
    result = nav.path(START, nav.features("exit")[0], ())
    assert isinstance(result, NoPath)
    assert "other side" in result.reason


def test_that_door_is_a_route_from_the_side_that_has_the_use_face_and_once_it_is_open():
    nav = one_face_nav("b")
    assert isinstance(nav.path((400.0, 128.0), (100.0, 100.0), ()), Route)
    assert isinstance(
        nav.path(START, nav.features("exit")[0], (), closed=frozenset()), Route
    )  # already open


def test_walking_up_to_a_door_stops_on_a_side_where_it_can_be_used():
    nav = one_face_nav("b")
    route = nav.path((400.0, 128.0), nav.features("door")[0], ())
    assert isinstance(route, Route) and route.waypoints[-1].x > 272  # room B's side
    assert isinstance(
        nav.path(START, nav.features("door")[0], ()), NoPath
    )  # room A's side is no use


def test_two_unreachable_features_at_the_same_spot_still_get_a_reason():
    nav = navmap(door_special=None)
    twins = [Feature("object", "A", 400.0, 128.0), Feature("object", "B", 400.0, 128.0)]
    result = nav.nearest(START, twins, ())
    assert isinstance(result, NoPath) and "no route" in result.reason


def test_starting_inside_the_door_keeps_the_door_flag_on_the_first_waypoint():
    nav = navmap()
    route = nav.path((264.0, 128.0), exit_feature(nav), ())
    assert isinstance(route, Route) and route.doors == 1
    assert route.waypoints[0].door_sector == DOOR
