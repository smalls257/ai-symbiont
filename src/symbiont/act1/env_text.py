"""State to text: what the player sees, written for a language model.

ViZDoom's object labels leave out walls, doors and openings, so a label-only
description reads "nothing notable" in a third of observations (day-1 probe:
12 of 40). The layout is therefore derived from the depth buffer and the door
list from sector heights. Everything here is pure over plain data: the
periphery (episode.py) builds a `GameStateView` from the engine, this module
never touches the engine. Bearings are degrees, positive to the left.
"""

import math
from dataclasses import dataclass

import numpy as np

from symbiont.act1.map_index import MapIndex, StaticDoor
from symbiont.act1.navmap import Feature, NavMap, NoPath, held_colours

KEY_NAMES = frozenset({"BlueCard", "RedCard", "YellowCard", "BlueSkull", "RedSkull", "YellowSkull"})
ENEMY_NAMES = frozenset(
    {
        "Zombieman",
        "ShotgunGuy",
        "ChaingunGuy",
        "DoomImp",
        "Imp",
        "Demon",
        "Spectre",
        "LostSoul",
        "Cacodemon",
        "BaronOfHell",
        "HellKnight",
        "Revenant",
        "Arachnotron",
        "Archvile",
        "Fatso",
        "Cyberdemon",
        "PainElemental",
        "SpiderMastermind",
        "WolfensteinSS",
    }
)

# Depth buffer is 8-bit: small is near, large is far, 1 at wall contact. Measured on Freedoom MAP01
# (walking at a wall): ~6 at 35 units, ~15 at 100, ~25 at 170, ~35 at 240, 60+ across a large room.
WALL_CLOSE_DEPTH = 15
OPEN_DEPTH = 25
# ViZDoom's default horizontal field of view is 90 degrees; doors outside it are not on screen.
SCREEN_FOV_HALF_DEG = 45.0
# Depth-buffer value expected at a given distance, interpolated from the measurements above.
DEPTH_AT_UNITS = (
    (35.0, 6.0),
    (100.0, 15.0),
    (170.0, 25.0),
    (240.0, 35.0),
    (400.0, 45.0),
    (880.0, 62.0),
)
# A door center sits behind its door face; only a clearly nearer surface in its column hides it.
OCCLUSION_RATIO = 0.6
DOOR_COLUMN_HALF_WIDTH = 8
AHEAD_BEARING_DEG = 5.0


@dataclass(frozen=True)
class SeenObject:
    """An object the engine reports in view, with its range and bearing from the player."""

    name: str
    distance: float
    bearing_deg: float

    @property
    def is_key(self) -> bool:
        """True for the six key pickups."""
        return self.name in KEY_NAMES

    @property
    def is_enemy(self) -> bool:
        """True for monsters that can hurt the player."""
        return self.name in ENEMY_NAMES


@dataclass(frozen=True)
class SeenDoor:
    """A closed door on screen; `key_colour` is set when it is locked."""

    distance: float
    bearing_deg: float
    key_colour: str | None = None


@dataclass(frozen=True)
class SeenExit:
    """A level exit on screen; `secret` marks the secret exit."""

    distance: float
    bearing_deg: float
    secret: bool = False


@dataclass(frozen=True)
class RouteHint:
    """The nearest door, exit or key of one kind by walking route, in view or not (see navmap)."""

    kind: str
    label: str
    path_units: float | None  # None: no route, and `blocked` says why
    doors: int
    blocked: str | None


@dataclass(frozen=True)
class Layout:
    """Open space and wall proximity read from the depth buffer."""

    left_open: bool
    ahead_open: bool
    right_open: bool
    wall_close_ahead: bool


@dataclass(frozen=True)
class GameStateView:
    """Everything `describe` needs, as plain data: the engine never reaches this module."""

    health: float
    ammo: float
    position: tuple[float, float]
    angle_deg: float
    objects: tuple[SeenObject, ...]
    doors: tuple[SeenDoor, ...]
    keys_held: tuple[str, ...]
    layout: Layout
    exits: tuple[SeenExit, ...] = ()
    # Closed doors within touching range, whether or not they are on screen or occluded: the
    # evidence for "this door opened" must not depend on the camera.
    reach_doors: tuple[SeenDoor, ...] = ()
    # Indexes of every sector whose ceiling has dropped to its floor, seen or not: how a mover knows
    # a door ahead is shut.
    closed_sectors: frozenset[int] = frozenset()
    routes: tuple[RouteHint, ...] = ()


def normalize_degrees(angle: float) -> float:
    """Fold any angle into (-180, 180]."""
    folded = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if folded == -180.0 else folded


def layout_from_depth(depth: np.ndarray) -> Layout:
    """Open space left/ahead/right and wall-close-ahead from an 8-bit depth buffer."""
    rows, cols = depth.shape
    band = depth[rows // 3 : 2 * rows // 3]
    third = cols // 3
    left = float(np.median(band[:, :third]))
    ahead = float(np.median(band[:, third : 2 * third]))
    right = float(np.median(band[:, 2 * third :]))
    return Layout(
        left_open=left >= OPEN_DEPTH,
        ahead_open=ahead >= OPEN_DEPTH,
        right_open=right >= OPEN_DEPTH,
        wall_close_ahead=ahead < WALL_CLOSE_DEPTH,
    )


def expected_depth(distance: float) -> float:
    """Depth-buffer value a surface at `distance` units should show, from the measured table."""
    units, depths = zip(*DEPTH_AT_UNITS, strict=True)
    return float(np.interp(distance, units, depths))


def _depth_at_bearing(depth: np.ndarray, bearing_deg: float) -> float:
    rows, cols = depth.shape
    tan_ratio = math.tan(math.radians(bearing_deg)) / math.tan(math.radians(SCREEN_FOV_HALF_DEG))
    center = int(round(cols / 2 * (1 - tan_ratio)))  # positive bearing is left of center
    lo = max(0, center - DOOR_COLUMN_HALF_WIDTH)
    hi = min(cols, center + DOOR_COLUMN_HALF_WIDTH + 1)
    return float(np.median(depth[rows // 3 : 2 * rows // 3, lo:hi]))


def _bearing_and_distance(
    mid: tuple[float, float], position: tuple[float, float], angle_deg: float
) -> tuple[float, float]:
    dx, dy = mid[0] - position[0], mid[1] - position[1]
    return normalize_degrees(math.degrees(math.atan2(dy, dx)) - angle_deg), math.hypot(dx, dy)


def _one_per_sector(
    doors: list[tuple[StaticDoor, float, float]],
) -> list[tuple[StaticDoor, float, float]]:
    """A door has a line on each face; keep the nearest line per door sector."""
    nearest: dict[object, tuple[StaticDoor, float, float]] = {}
    for entry in doors:
        key = entry[0].sector if entry[0].sector is not None else ("line", entry[0].line)
        if key not in nearest or entry[2] < nearest[key][2]:
            nearest[key] = entry
    return sorted(nearest.values(), key=lambda found: found[2])


def _on_screen_unoccluded(bearing: float, distance: float, depth: np.ndarray) -> bool:
    if abs(bearing) >= SCREEN_FOV_HALF_DEG:
        return False
    return _depth_at_bearing(depth, bearing) >= OCCLUSION_RATIO * expected_depth(distance)


@dataclass(frozen=True)
class Viewpoint:
    """Where the player stands and which way they face, in map units and degrees."""

    position: tuple[float, float]
    angle_deg: float


def _visible_doors(
    index: MapIndex,
    closed_sectors: frozenset[int],
    view: Viewpoint,
    depth: np.ndarray,
    max_distance: float,
) -> tuple[SeenDoor, ...]:
    candidates = []
    for door in index.doors:
        if door.sector not in closed_sectors:
            continue
        bearing, distance = _bearing_and_distance(door.mid, view.position, view.angle_deg)
        if distance <= max_distance and _on_screen_unoccluded(bearing, distance, depth):
            candidates.append((door, bearing, distance))
    return tuple(
        SeenDoor(distance, bearing, door.key_colour)
        for door, bearing, distance in _one_per_sector(candidates)
    )


def _visible_exits(
    index: MapIndex, view: Viewpoint, depth: np.ndarray, max_distance: float
) -> tuple[SeenExit, ...]:
    exits = []
    for exit_ in index.exits:
        bearing, distance = _bearing_and_distance(exit_.mid, view.position, view.angle_deg)
        if distance <= max_distance and _on_screen_unoccluded(bearing, distance, depth):
            exits.append(SeenExit(distance, bearing, exit_.secret))
    return tuple(sorted(exits, key=lambda seen: seen.distance))


def locate_features(
    index: MapIndex,
    closed_sectors: frozenset[int],
    view: Viewpoint,
    depth: np.ndarray,
    max_distance: float,
) -> tuple[tuple[SeenDoor, ...], tuple[SeenExit, ...]]:
    """Closed doors and exits in view: inside the screen FOV, not behind a nearer wall.

    Positions come from the map's own linedefs (see map_index), so a listed door is a real door.
    """
    doors = _visible_doors(index, closed_sectors, view, depth, max_distance)
    return doors, _visible_exits(index, view, depth, max_distance)


def doors_in_reach(
    index: MapIndex,
    closed_sectors: frozenset[int],
    position: tuple[float, float],
    reach: float,
) -> tuple[SeenDoor, ...]:
    """Closed doors within `reach` units; the camera is ignored so the world judges opening."""
    near = []
    for door in index.doors:
        if door.sector not in closed_sectors:
            continue
        bearing, distance = _bearing_and_distance(door.mid, position, 0.0)
        if distance <= reach:
            near.append((door, bearing, distance))
    return tuple(SeenDoor(dist, 0.0, d.key_colour) for d, _, dist in _one_per_sector(near))


def _direction(bearing_deg: float) -> str:
    if abs(bearing_deg) < AHEAD_BEARING_DEG:
        return "straight ahead"
    side = "left" if bearing_deg > 0 else "right"
    return f"{abs(bearing_deg):.1f} degrees to the {side}"


def _describe_layout(layout: Layout) -> str:
    parts = []
    if layout.wall_close_ahead:
        parts.append("wall close ahead")
    elif layout.ahead_open:
        parts.append("open space ahead")
    if layout.left_open:
        parts.append("open to the left")
    if layout.right_open:
        parts.append("open to the right")
    return "Layout: " + (", ".join(parts) if parts else "walls on every side") + "."


def _describe_object(obj: SeenObject) -> str:
    label = " (key)" if obj.is_key else " (enemy)" if obj.is_enemy else ""
    return f"{obj.name}{label} {obj.distance:.1f} units, {_direction(obj.bearing_deg)}"


def _describe_door(door: SeenDoor) -> str:
    needs = f" (needs {door.key_colour} key)" if door.key_colour else ""
    return f"closed door{needs} {door.distance:.1f} units, {_direction(door.bearing_deg)}"


def _describe_exit(exit_: SeenExit) -> str:
    kind = "secret exit" if exit_.secret else "exit"
    return f"{kind} {exit_.distance:.1f} units, {_direction(exit_.bearing_deg)}"


def route_hints(nav: NavMap, state: GameStateView) -> tuple[RouteHint, ...]:
    """Nearest closed door, unfetched key and exit by walking route, in view or not."""
    held = held_colours(state.keys_held)
    exits = nav.features("exit")
    pools = {
        "door": [d for d in nav.features("door") if d.door_sector in state.closed_sectors],
        "key": [k for k in nav.features("key") if k.key_colour not in held],
        "exit": [e for e in exits if not e.secret] or list(exits),
    }
    return tuple(_hint_for(nav, state, kind, pool) for kind, pool in pools.items() if pool)


def _hint_for(nav: NavMap, state: GameStateView, kind: str, candidates: list[Feature]) -> RouteHint:
    found = nav.nearest(state.position, candidates, state.keys_held, state.closed_sectors)
    if isinstance(found, NoPath):
        return RouteHint(kind, _route_label(kind, candidates[0]), None, 0, found.reason)
    feature, route = found
    return RouteHint(kind, _route_label(kind, feature), route.length, route.doors, None)


def _route_label(kind: str, feature: Feature) -> str:
    if kind == "door" and feature.key_colour:
        return f"door (needs {feature.key_colour} key)"
    return feature.label


def _describe_route(hint: RouteHint) -> str:
    if hint.path_units is None:
        return f"{hint.label}: no route ({hint.blocked})"
    through = f", through {hint.doors} door{'s' if hint.doors != 1 else ''}" if hint.doors else ""
    return f"{hint.label}: {hint.path_units:,.0f} units by path{through}"


def _listing(label: str, sentences: list[str]) -> list[str]:
    return [f"{label}: " + "; ".join(sentences) + "."] if sentences else []


def describe(state: GameStateView) -> str:
    """The observation the model reads: status, layout, then what is in view and reachable."""
    sentences = [f"Player: health {int(state.health)}, ammo {int(state.ammo)}."]
    if state.keys_held:
        sentences.append("Keys held: " + ", ".join(state.keys_held) + ".")
    sentences.append(_describe_layout(state.layout))
    objects = [
        _describe_object(seen) for seen in sorted(state.objects, key=lambda seen: seen.distance)
    ]
    doors = [_describe_door(door) for door in sorted(state.doors, key=lambda door: door.distance)]
    exits = [
        _describe_exit(exit_) for exit_ in sorted(state.exits, key=lambda exit_: exit_.distance)
    ]
    sentences += _listing("Visible", objects)
    sentences += _listing("Doors", doors)
    sentences += _listing("Exits", exits)
    if not (objects or doors or exits):
        sentences.append("No objects, doors or exits in view.")
    sentences += _listing("Reachable with go_to", [_describe_route(r) for r in state.routes])
    return " ".join(sentences)
