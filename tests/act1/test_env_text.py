import math
import re

import numpy as np

from symbiont.act1.env_text import (
    GameStateView,
    Layout,
    SeenDoor,
    SeenExit,
    SeenObject,
    Viewpoint,
    describe,
    doors_in_reach,
    layout_from_depth,
    locate_features,
)
from symbiont.act1.map_index import build_index
from symbiont.act1.wad import read_map
from wad_builder import sample_wad

OPEN_LAYOUT = Layout(left_open=True, ahead_open=True, right_open=True, wall_close_ahead=False)


def make_state(**overrides) -> GameStateView:
    fields = dict(
        health=87,
        ammo=26,
        position=(100.0, 200.0),
        angle_deg=90.0,
        objects=(),
        doors=(),
        keys_held=(),
        layout=OPEN_LAYOUT,
    )
    fields.update(overrides)
    return GameStateView(**fields)


def test_describe_lists_keys_and_doors():
    state = make_state(
        objects=(
            SeenObject(name="BlueCard", distance=210.4, bearing_deg=-12.0),
            SeenObject(name="Zombieman", distance=300.0, bearing_deg=35.0),
        ),
        doors=(SeenDoor(distance=96.0, bearing_deg=0.0),),
        keys_held=("RedCard",),
    )
    text = describe(state)
    assert "BlueCard" in text and "key" in text.lower()
    assert "door" in text.lower() and "closed" in text.lower()
    assert "Zombieman" in text
    assert "RedCard" in text
    assert "health 87" in text and "ammo 26" in text


def test_describe_no_floats_beyond_one_decimal():
    state = make_state(
        health=87.123456,
        position=(100.123456, 200.987654),
        objects=(SeenObject(name="Imp", distance=123.456789, bearing_deg=-33.333333),),
        doors=(SeenDoor(distance=77.777777, bearing_deg=11.111111),),
    )
    text = describe(state)
    assert not re.search(r"\d+\.\d{2,}", text)


def test_describe_empty_scene_is_not_nothing_notable():
    walled = make_state(
        layout=Layout(left_open=True, ahead_open=False, right_open=False, wall_close_ahead=True)
    )
    text = describe(walled)
    assert "nothing notable" not in text
    assert "wall" in text.lower()
    assert "left" in text.lower()


def test_describe_is_deterministic_and_orders_nearest_first():
    far = SeenObject(name="Imp", distance=500.0, bearing_deg=0.0)
    near = SeenObject(name="Zombieman", distance=100.0, bearing_deg=0.0)
    text = describe(make_state(objects=(far, near)))
    assert text.index("Zombieman") < text.index("Imp")
    assert describe(make_state(objects=(far, near))) == text


def test_bearing_wording_distinguishes_left_and_right():
    left = describe(make_state(objects=(SeenObject("Imp", 100.0, 40.0),)))
    right = describe(make_state(objects=(SeenObject("Imp", 100.0, -40.0),)))
    assert "left" in left.split("Imp")[1]
    assert "right" in right.split("Imp")[1]


def test_layout_from_depth_sees_wall_ahead_and_open_sides():
    # 8-bit depth: small = near, large = far.
    depth = np.full((240, 320), 60, dtype=np.uint8)
    depth[:, 107:213] = 8  # wall close in the centre third
    layout = layout_from_depth(depth)
    assert layout.wall_close_ahead
    assert not layout.ahead_open
    assert layout.left_open and layout.right_open


def test_layout_from_depth_blocked_left():
    depth = np.full((240, 320), 60, dtype=np.uint8)
    depth[:, :107] = 8
    layout = layout_from_depth(depth)
    assert not layout.left_open
    assert layout.ahead_open and layout.right_open
    assert not layout.wall_close_ahead


def clear_depth() -> np.ndarray:
    return np.full((240, 320), 60, dtype=np.uint8)


def sample_index():
    return build_index(read_map(sample_wad(), "MAP01"))


# sample map: blue door line 0 mid (100, 32); plain door line 1 mid (32, 200); both in sector 1;
# exit line 2 mid (300, 32); secret exit line 3 mid (32, 0).
ALL_CLOSED = frozenset({1})


def facing(position, target):
    return math.degrees(math.atan2(target[1] - position[1], target[0] - position[0]))


def test_locate_features_lists_doors_with_key_colour_and_exits_in_view():
    position = (0.0, 32.0)
    doors, exits = locate_features(
        sample_index(), ALL_CLOSED, Viewpoint(position, 0.0), clear_depth(), 600.0
    )
    assert [(round(d.distance), d.key_colour) for d in doors] == [(100, "blue")]
    assert abs(doors[0].bearing_deg) < 0.1
    assert [(round(e.distance), e.secret) for e in exits] == [(300, False)]


def test_locate_features_drops_a_door_behind_a_near_wall():
    wall = clear_depth()
    wall[:, 120:200] = 8
    doors, exits = locate_features(
        sample_index(), ALL_CLOSED, Viewpoint((0.0, 32.0), 0.0), wall, 600.0
    )
    assert doors == () and exits == ()


def test_locate_features_drops_features_outside_the_screen_fov():
    # facing +y from (-100, 32): the blue door is 90 degrees off to the right, off screen.
    doors, _ = locate_features(
        sample_index(), ALL_CLOSED, Viewpoint((-100.0, 32.0), 90.0), clear_depth(), 600.0
    )
    assert [d.key_colour for d in doors] == [
        None
    ]  # only the plain door, at -38 degrees, is on screen


def test_locate_features_omits_a_door_whose_sector_has_opened():
    doors, _ = locate_features(
        sample_index(), frozenset(), Viewpoint((0.0, 32.0), 0.0), clear_depth(), 600.0
    )
    assert doors == ()


def test_doors_in_reach_merges_doors_that_share_a_sector():
    # Both sample door lines border sector 1 (two faces of one door) and are 90 units from here.
    assert len(doors_in_reach(sample_index(), ALL_CLOSED, (66.0, 116.0), 96.0)) == 1


def test_doors_in_reach_ignores_the_camera_and_the_door_state_gate():
    assert [
        d.key_colour for d in doors_in_reach(sample_index(), ALL_CLOSED, (110.0, 32.0), 96.0)
    ] == ["blue"]
    assert doors_in_reach(sample_index(), frozenset(), (110.0, 32.0), 96.0) == ()
    assert doors_in_reach(sample_index(), ALL_CLOSED, (600.0, 600.0), 96.0) == ()


def test_describe_lists_exit_and_door_key_requirement():
    state = make_state(
        doors=(SeenDoor(distance=96.0, bearing_deg=0.0, key_colour="blue"),),
        exits=(SeenExit(distance=250.0, bearing_deg=-20.0, secret=False),),
    )
    text = describe(state)
    assert "needs blue key" in text
    assert "exit" in text.lower() and "250.0" in text
