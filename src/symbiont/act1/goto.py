"""go_to: walk a route planned over the map's walls and doors (scripted, never learned).

The move is a function of the current `GameStateView`, like every move in moves.py, plus the level's
`NavMap`. It stops, saying why, whenever it cannot go on: no map, no path, a door that will not
open, no progress, an enemy within reach in view, or an exhausted tic budget. It never retries.
The enemy stop exists because the strategy, not the walking script, decides whether to fight.
"""

import math
from dataclasses import dataclass, field

from symbiont.act1.env_text import GameStateView, SeenObject, normalize_degrees
from symbiont.act1.moves import (
    DOOR_NAMES,
    FACING_TOLERANCE_DEG,
    USE_TICS,
    Button,
    Done,
    OpenDoor,
    StepResult,
    find_visible,
    hold,
    turn_toward,
)
from symbiont.act1.navmap import Feature, NavMap, NoPath, Waypoint
from symbiont.act1.navtypes import held_colours

GO_TO_MAX_TICS = 2500
WAYPOINT_ARRIVAL_UNITS = 24.0
STUCK_FORWARD_TICS = 45  # a door needs ~28 tics to rise far enough to walk through
STUCK_MIN_PROGRESS_UNITS = 16.0
EXIT_FACING_DEG = 5.0
# [measured] MAP01, ViZDoom 1.3.2: a clean go_to(exit) walked into monster fire and reached the exit
# on 5 of 8 seeds; handing control back at 256 units (with shoot_nearest() first) reached it on 8 of
# 8, while 512 units reached it on 3 of 8 because the move quit for enemies too far away to hit.
ENEMY_IN_THE_WAY_UNITS = 256.0


@dataclass
class GoTo:
    """Walk a route planned over the map's walls and doors to a door, exit, key or visible object.

    Closed doors on the route are opened with OpenDoor; the move stops, saying why, when there is no
    path, a door will not open, walking makes no progress, an enemy is within reach, or the tic
    budget runs out. It never retries. At an exit it faces the switch and presses USE, since
    reaching the wall alone does not end the level.
    """

    target: str
    nav: NavMap | None = None
    max_tics = GO_TO_MAX_TICS
    _goal: Feature | None = field(default=None, init=False, repr=False, compare=False)
    _waypoints: tuple[Waypoint, ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _next: int = field(default=0, init=False, repr=False, compare=False)
    _opener: OpenDoor | None = field(default=None, init=False, repr=False, compare=False)
    _tics: int = field(default=0, init=False, repr=False, compare=False)
    _anchor: tuple[float, float] | None = field(default=None, init=False, repr=False, compare=False)
    _forward_tics: int = field(default=0, init=False, repr=False, compare=False)
    _exit_tics: int = field(default=0, init=False, repr=False, compare=False)

    @property
    def label(self) -> str:
        """Names the move as scripted in every log line."""
        return f"scripted go_to({self.target})"

    def step(self, state: GameStateView) -> StepResult:
        """Plan once, then follow the waypoints, opening doors; Done says why it stopped."""
        self._tics += 1
        if self._tics >= self.max_tics:
            return Done(f"out of tic budget ({self.max_tics}) {self._where()}")
        blocker = _nearest_enemy_in_reach(state)
        if blocker is not None:
            return Done(f"enemy in the way: {blocker.name} at {blocker.distance:.0f}")
        if self._waypoints is None:
            planned = self._plan(state)
            if isinstance(planned, Done):
                return planned
        if self._opener is not None:
            return self._keep_opening(state)
        return self._follow(state)

    def _where(self) -> str:
        """Where on the route the player is, for a stop message."""
        if self._waypoints is None:
            return "before a route was planned"
        return f"at waypoint {min(self._next + 1, len(self._waypoints))} of {len(self._waypoints)}"

    # --- planning ---------------------------------------------------------------------------

    def _plan(self, state: GameStateView) -> Done | None:
        """Plan a route to the nearest reachable candidate; Done when there is none."""
        if self.nav is None:
            return Done("no map loaded: go_to needs the level's walls and doors")
        candidates = candidate_features(self.nav, self.target, state)
        if isinstance(candidates, Done):
            return candidates
        found = self.nav.nearest(state.position, candidates, state.keys_held, state.closed_sectors)
        if isinstance(found, NoPath):
            return Done(f"no path to {self.target}: {found.reason}")
        self._goal, route = found
        self._waypoints = route.waypoints
        return None

    # --- walking ----------------------------------------------------------------------------

    def _follow(self, state: GameStateView) -> StepResult:
        """Steer toward the next waypoint, open a door on the way, or finish at the goal."""
        assert self._waypoints is not None and self._goal is not None
        if self._next >= len(self._waypoints):
            return self._at_goal(state)
        waypoint = self._waypoints[self._next]
        if math.dist(state.position, (waypoint.x, waypoint.y)) > WAYPOINT_ARRIVAL_UNITS:
            return self._steer(state, waypoint)
        if waypoint.door_sector in state.closed_sectors:
            self._opener = OpenDoor()
            return self._keep_opening(state)
        self._next += 1
        return self._follow(state)

    def _keep_opening(self, state: GameStateView) -> StepResult:
        """Keep opening the door in the way; Done when opening fails."""
        assert self._opener is not None
        result = self._opener.step(state)
        if not isinstance(result, Done):
            return result
        if not result.succeeded:
            return Done(f"stopped at door {self._where()}: {result.reason}")
        self._opener = None
        self._next += 1
        return self._follow(state)

    def _steer(self, state: GameStateView, waypoint: Waypoint) -> StepResult:
        """Turn toward the waypoint, then walk."""
        bearing = _bearing_to(state, (waypoint.x, waypoint.y))
        if abs(bearing) > FACING_TOLERANCE_DEG:
            return turn_toward(bearing)
        return self._forward(state, waypoint)

    def _forward(self, state: GameStateView, waypoint: Waypoint) -> StepResult:
        """Walk forward; Done when STUCK_FORWARD_TICS tics made too little progress."""
        if self._anchor is None:
            self._anchor = state.position
        self._forward_tics += 1
        if self._forward_tics >= STUCK_FORWARD_TICS:
            moved = math.dist(state.position, self._anchor)
            if moved < STUCK_MIN_PROGRESS_UNITS:
                return Done(
                    f"stuck at {state.position[0]:.0f},{state.position[1]:.0f} {self._where()} "
                    f"({waypoint.x:.0f},{waypoint.y:.0f}): "
                    f"no progress in {STUCK_FORWARD_TICS} forward tics"
                )
            self._anchor, self._forward_tics = state.position, 0
        return hold(Button.FORWARD)

    def _at_goal(self, state: GameStateView) -> StepResult:
        """Arrive at the goal; at an exit, face it and press USE, Done if the level never ends."""
        assert self._goal is not None
        if self._goal.kind != "exit":
            return Done(f"arrived at {self._goal.label}")
        bearing = _bearing_to(state, (self._goal.x, self._goal.y))
        if abs(bearing) > EXIT_FACING_DEG:
            return turn_toward(bearing)
        self._exit_tics += 1
        if self._exit_tics > USE_TICS:
            return Done("reached exit and pressed USE, but the level did not end")
        return hold(Button.USE) if self._exit_tics % 2 == 1 else hold()


def _nearest_enemy_in_reach(state: GameStateView) -> SeenObject | None:
    """The nearest enemy close enough to block the route, if any."""
    near = [
        seen for seen in state.objects if seen.is_enemy and seen.distance <= ENEMY_IN_THE_WAY_UNITS
    ]
    return min(near, key=lambda seen: seen.distance, default=None)


def _bearing_to(state: GameStateView, point: tuple[float, float]) -> float:
    """Degrees to turn so the player faces `point`, folded into (-180, 180]."""
    heading = math.degrees(math.atan2(point[1] - state.position[1], point[0] - state.position[0]))
    return normalize_degrees(heading - state.angle_deg)


def candidate_features(nav: NavMap, target: str, state: GameStateView) -> list[Feature] | Done:
    """What `go_to(target)` may end at: exit, closed doors, unheld keys, or a visible object."""
    name = target.lower()
    if name == "exit":
        return _exits(nav)
    if name in DOOR_NAMES:
        return _closed_doors(nav, state)
    if name == "key":
        return _unheld_keys(nav, state)
    return _named_key(nav, name) or _visible_object(target, state)


def _exits(nav: NavMap) -> list[Feature]:
    """The level's normal exits, or its secret ones when it has no other."""
    exits = nav.features("exit")
    return [e for e in exits if not e.secret] or list(exits)


def _closed_doors(nav: NavMap, state: GameStateView) -> list[Feature] | Done:
    """Door features that are closed right now, or Done when none is."""
    doors = [d for d in nav.features("door") if d.door_sector in state.closed_sectors]
    return doors or Done("no closed door to go to")


def _named_key(nav: NavMap, name: str) -> list[Feature]:
    """Key features whose label is `name`."""
    return [k for k in nav.features("key") if k.label.lower() == name]


def _unheld_keys(nav: NavMap, state: GameStateView) -> list[Feature] | Done:
    """Key features the player does not hold, or Done when every key is held."""
    held = held_colours(state.keys_held)
    fetchable = [k for k in nav.features("key") if k.key_colour not in held]
    return fetchable or Done(f"no key left to fetch: {', '.join(sorted(held)) or 'none'} is held")


def _visible_object(target: str, state: GameStateView) -> list[Feature] | Done:
    """The visible object named `target` as a map feature, or Done when it is not seen."""
    seen = find_visible(state, target)
    if seen is None:
        return Done(f"{target} not visible, and it is not a door, exit or key on the map")
    heading = math.radians(state.angle_deg + seen.bearing_deg)
    x = state.position[0] + seen.distance * math.cos(heading)
    y = state.position[1] + seen.distance * math.sin(heading)
    return [Feature("object", seen.name, x, y)]
