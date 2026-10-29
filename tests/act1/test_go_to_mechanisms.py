import math

from nav_mech_world import START, switch_door, teleport
from symbiont.act1.env_text import GameStateView, Layout, normalize_degrees
from symbiont.act1.goto import GoTo
from symbiont.act1.map_index import build_index
from symbiont.act1.moves import Button, Done
from symbiont.act1.navmap import build_navmap

OPEN = Layout(True, True, True, False)
SWITCH_AIM = (120.0, 256.0)
TURN_DEG, STEP_UNITS = 4.0, 8.0


class FreeWalker:
    """A player with no walls: turns 4 degrees, walks 8 units a tic, teleports on request.

    `presses` records the tics on which USE was held within reach of the switch and facing it.
    """

    def __init__(self, teleport_from=None, teleport_to=None):
        self.x, self.y = START
        self.angle = 0.0
        self.presses = 0
        self.teleport_from, self.teleport_to = teleport_from, teleport_to

    def view(self) -> GameStateView:
        return GameStateView(100, 10, (self.x, self.y), self.angle, (), (), (), OPEN)

    def act(self, buttons) -> None:
        if Button.TURN_LEFT in buttons:
            self.angle = normalize_degrees(self.angle + TURN_DEG)
        if Button.TURN_RIGHT in buttons:
            self.angle = normalize_degrees(self.angle - TURN_DEG)
        if Button.USE in buttons and self._facing(SWITCH_AIM) and self._near(SWITCH_AIM, 64):
            self.presses += 1
        if Button.FORWARD in buttons:
            self.x += STEP_UNITS * math.cos(math.radians(self.angle))
            self.y += STEP_UNITS * math.sin(math.radians(self.angle))
            if self.teleport_from and self._near(self.teleport_from, 30):
                self.x, self.y = self.teleport_to

    def _near(self, point, units):
        return math.dist((self.x, self.y), point) <= units

    def _facing(self, point):
        heading = math.degrees(math.atan2(point[1] - self.y, point[0] - self.x))
        return abs(normalize_degrees(heading - self.angle)) <= 10


def run(move, walker, limit=4000):
    for _ in range(limit):
        result = move.step(walker.view())
        if isinstance(result, Done):
            return result.reason
        walker.act(result)
    raise AssertionError("move never finished")


def nav_of(geometry):
    return build_navmap(geometry, build_index(geometry))


def test_go_to_exit_presses_the_switch_that_opens_the_door_before_walking_through():
    walker = FreeWalker()
    reason = run(GoTo("exit", nav_of(switch_door())), walker)
    assert reason.startswith("reached exit")
    assert walker.presses >= 1  # the switch was pressed facing it, not walked past


def test_go_to_exit_follows_a_teleport_to_the_far_room():
    # the pad's west edge is x=192; the walker is flung to the landing in the far room on crossing
    walker = FreeWalker(teleport_from=(210.0, 112.0), teleport_to=(500.0, 128.0))
    reason = run(GoTo("exit", nav_of(teleport())), walker)
    assert reason.startswith("reached exit")
    assert walker.x > 400


def test_a_walkover_exit_is_crossed_not_pressed():
    walker = FreeWalker()
    reason = run(GoTo("exit", nav_of(switch_door(exit_special=52))), walker)
    assert reason.startswith("walked across the exit line")
    assert walker.x > 528  # past the east wall's line, where the level would have ended
