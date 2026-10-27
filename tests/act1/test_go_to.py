import math
from enum import Enum

import pytest

from nav_world import CARD, DOOR, EXIT_MID, START, two_rooms, two_rooms_index
from symbiont.act1.env_text import (
    GameStateView,
    Layout,
    RouteHint,
    SeenDoor,
    SeenObject,
    describe,
    normalize_degrees,
)
from symbiont.act1.goto import GoTo
from symbiont.act1.moves import Button, Done
from symbiont.act1.navmap import build_navmap
from symbiont.act1.strategy import StrategyError, parse_strategy

OPEN = Layout(True, True, True, False)
DOOR_CENTRE = (264.0, 128.0)
TURN_DEG, STEP_UNITS = 4.0, 8.0


def make_nav(**kwargs):
    geometry = two_rooms(**kwargs)
    return build_navmap(geometry, two_rooms_index(geometry)[1])


class Fault(Enum):
    DOOR_JAMS = "door_jams"
    FROZEN = "frozen"


class Sim:
    """A free-walking player: turns 4 degrees and walks 8 units a tic.

    The door blocks while closed and opens on USE when faced within reach, unless the fault is
    DOOR_JAMS. FROZEN makes FORWARD do nothing.
    """

    def __init__(self, keys=(), fault=None, objects=()):
        self.x, self.y = START
        self.angle = 0.0
        self.closed = frozenset({DOOR})
        self.keys, self.fault, self.objects = tuple(keys), fault, tuple(objects)
        self.used = 0

    def view(self) -> GameStateView:
        bearing = normalize_degrees(
            math.degrees(math.atan2(DOOR_CENTRE[1] - self.y, DOOR_CENTRE[0] - self.x)) - self.angle
        )
        distance = math.dist((self.x, self.y), DOOR_CENTRE)
        door = [SeenDoor(distance, bearing)] if self.closed else []
        seen = [
            SeenObject(
                name,
                math.dist((self.x, self.y), p),
                normalize_degrees(
                    math.degrees(math.atan2(p[1] - self.y, p[0] - self.x)) - self.angle
                ),
            )
            for name, p in self.objects
        ]
        return GameStateView(
            100,
            10,
            (self.x, self.y),
            self.angle,
            tuple(seen),
            tuple(door if abs(bearing) < 45 else []),
            self.keys,
            OPEN,
            reach_doors=tuple(door if distance <= 96 else []),
            closed_sectors=self.closed,
        )

    def act(self, buttons) -> None:
        if Button.TURN_LEFT in buttons:
            self.angle = normalize_degrees(self.angle + TURN_DEG)
        if Button.TURN_RIGHT in buttons:
            self.angle = normalize_degrees(self.angle - TURN_DEG)
        if Button.USE in buttons:
            self.used += 1
            view = self.view()
            if (
                view.reach_doors
                and abs(view.reach_doors[0].bearing_deg) <= 10
                and self.fault is not Fault.DOOR_JAMS
            ):
                self.closed = frozenset()
        if Button.FORWARD in buttons and self.fault is not Fault.FROZEN:
            nx = self.x + STEP_UNITS * math.cos(math.radians(self.angle))
            ny = self.y + STEP_UNITS * math.sin(math.radians(self.angle))
            crossing_door = self.closed and 256 <= nx <= 272 and 96 <= ny <= 160
            if not crossing_door:
                self.x, self.y = nx, ny


def run(move, sim, limit=3000):
    for _ in range(limit):
        result = move.step(sim.view())
        if isinstance(result, Done):
            return result.reason
        sim.act(result)
    raise AssertionError("move never finished")


def test_go_to_exit_opens_the_door_on_the_way_and_stops_at_the_exit():
    sim = Sim()
    reason = run(GoTo("exit", make_nav()), sim)
    assert reason.startswith("reached exit")
    assert math.dist((sim.x, sim.y), EXIT_MID) <= 48
    assert sim.closed == frozenset()  # the door was opened by the move, not by the test


def test_go_to_exit_presses_use_facing_the_exit_switch():
    sim = Sim()
    run(GoTo("exit", make_nav()), sim)
    assert sim.used >= 1
    facing = normalize_degrees(
        math.degrees(math.atan2(EXIT_MID[1] - sim.y, EXIT_MID[0] - sim.x)) - sim.angle
    )
    assert abs(facing) <= 10


def test_go_to_stops_with_a_reason_when_the_door_will_not_open():
    reason = run(GoTo("exit", make_nav()), Sim(fault=Fault.DOOR_JAMS))
    assert reason.startswith("stopped at door")
    assert "did not open" in reason


def test_go_to_stops_with_a_reason_when_walking_makes_no_progress():
    reason = run(GoTo("exit", make_nav()), Sim(fault=Fault.FROZEN))
    assert reason.startswith("stuck") and "no progress" in reason


def test_go_to_locked_exit_route_names_the_colour_without_moving():
    move = GoTo("exit", make_nav(door_special=26))
    result = move.step(Sim().view())
    assert isinstance(result, Done)
    assert "no path to exit" in result.reason and "blue" in result.reason


def test_go_to_with_the_key_held_goes_through_the_locked_door():
    sim = Sim(keys=["BlueCard"])
    assert run(GoTo("exit", make_nav(door_special=26)), sim).startswith("reached exit")


def test_go_to_is_bounded_by_its_tic_budget(monkeypatch):
    monkeypatch.setattr(GoTo, "max_tics", 12)
    reason = run(GoTo("exit", make_nav()), Sim())
    assert reason.startswith("out of tic budget") and "waypoint" in reason


def test_go_to_door_walks_up_to_the_door_without_opening_it():
    sim = Sim()
    assert run(GoTo("door", make_nav()), sim) == "arrived at door"
    assert sim.closed == frozenset({DOOR}) and sim.x < 256


def test_go_to_key_reaches_a_key_that_is_out_of_sight():
    sim = Sim()
    assert run(GoTo("key", make_nav()), sim) == "arrived at BlueCard"
    assert math.dist((sim.x, sim.y), CARD) <= 24


def test_go_to_key_by_name_and_when_the_key_is_already_held():
    assert run(GoTo("BlueCard", make_nav()), Sim()) == "arrived at BlueCard"
    assert (
        run(GoTo("key", make_nav()), Sim(keys=["BlueCard"])) == "no key left to fetch: blue is held"
    )


def test_go_to_a_visible_object_routes_to_where_it_is():
    sim = Sim(objects=[("Stimpack", (200.0, 200.0))])
    assert run(GoTo("Stimpack", make_nav()), sim) == "arrived at Stimpack"
    assert math.dist((sim.x, sim.y), (200, 200)) <= 24


def test_go_to_an_unknown_target_stops_saying_so():
    reason = run(GoTo("Banana", make_nav()), Sim())
    assert "Banana" in reason and "not visible" in reason


def test_go_to_without_a_map_says_so_instead_of_guessing():
    assert "no map" in run(GoTo("exit"), Sim())


def test_go_to_door_when_none_is_closed():
    sim = Sim()
    sim.closed = frozenset()
    assert run(GoTo("door", make_nav()), sim) == "no closed door to go to"


def test_go_to_label_is_scripted_and_the_parser_accepts_it():
    nav = make_nav()
    [move] = parse_strategy("go_to(exit)", nav)
    assert isinstance(move, GoTo) and move.nav is nav
    assert move.label == "scripted go_to(exit)"
    assert [m.target for m in parse_strategy("go_to(door); go_to(BlueCard)")] == [
        "door",
        "BlueCard",
    ]


def test_parser_still_rejects_unknown_moves_and_bad_go_to_arguments():
    with pytest.raises(StrategyError, match="go_to"):
        parse_strategy("teleport(exit)")  # the allowed list now names go_to
    with pytest.raises(StrategyError):
        parse_strategy("go_to()")
    with pytest.raises(StrategyError):
        parse_strategy("go_to(a, b)")


def test_describe_lists_routes_by_path_even_when_nothing_is_in_view():
    state = Sim().view()
    hints = (
        RouteHint("exit", "exit", 1240.0, 1, None),
        RouteHint("door", "door", 300.0, 0, None),
        RouteHint("key", "BlueCard", None, 0, "locked door: needs red key on the way to BlueCard"),
    )
    text = describe(GameStateView(**{**state.__dict__, "doors": (), "routes": hints}))
    assert "exit: 1,240 units by path, through 1 door" in text
    assert "door: 300 units by path" in text and "through 0" not in text
    assert "BlueCard: no route (locked door: needs red key on the way to BlueCard)" in text
    assert "go_to" in text


def test_describe_without_routes_is_unchanged():
    assert "by path" not in describe(Sim().view())


def test_route_hints_name_the_nearest_closed_door_exit_and_key_by_path_with_blockers():
    from symbiont.act1.env_text import route_hints

    hints = {h.kind: h for h in route_hints(make_nav(door_special=26), Sim().view())}
    assert (
        hints["key"].label == "BlueCard"
        and hints["key"].path_units > 0
        and hints["key"].blocked is None
    )
    assert hints["door"].label == "door (needs blue key)" and hints["door"].path_units > 0
    assert hints["exit"].path_units is None and "blue" in hints["exit"].blocked
    with_key = {
        h.kind: h for h in route_hints(make_nav(door_special=26), Sim(keys=["BlueCard"]).view())
    }
    assert "key" not in with_key  # nothing left to fetch
    assert with_key["exit"].path_units > 400 and with_key["exit"].doors == 1


def test_route_hints_skip_doors_that_are_already_open():
    from symbiont.act1.env_text import route_hints

    sim = Sim()
    sim.closed = frozenset()
    assert "door" not in {h.kind for h in route_hints(make_nav(), sim.view())}
