"""Shared vocabulary of the navigation modules: what a route is made of (pure).

Why a module of its own: grid building, search, route shaping and diagnosis all speak these types,
and none of them may depend on another's internals (Shield).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

CELL = 8  # grid resolution in map units
USE_RANGE = 64.0  # how far a USE press reaches
KEY_REACH = 24.0
DOOR_REACH = 48.0
EXIT_REACH = 24.0

_COLOURS = ("blue", "yellow", "red")

Segment = tuple[float, float, float, float]


@dataclass(frozen=True)
class Feature:
    """Something a route can end at: a door, an exit, a key, or a point."""

    kind: str  # "door" | "exit" | "key" | "object"
    label: str
    x: float
    y: float
    reach: float = KEY_REACH  # a route ends on a free cell this close to (x, y)
    key_colour: str | None = None
    door_sector: int | None = None
    secret: bool = False
    # Lines (x1, y1, x2, y2) that carry the feature's use-special. USE works only from a line's
    # front side, so a route ends on the front side of one of them (empty: any side).
    faces: tuple[Segment, ...] = ()


@dataclass(frozen=True)
class Waypoint:
    """A point to walk to; `door_sector` is a shut door to open first."""

    x: float
    y: float
    # a closed door in front of this point must be opened before walking on
    door_sector: int | None = None


@dataclass(frozen=True)
class Route:
    """A walkable route: waypoints, length in map units, doors crossed."""

    waypoints: tuple[Waypoint, ...]
    length: float  # path length in map units
    doors: int  # doors crossed


@dataclass(frozen=True)
class NoPath:
    """No route exists; `reason` names what blocks it."""

    reason: str


def held_colours(keys_held: Iterable[str]) -> frozenset[str]:
    """Key colours from either colour words ("blue") or object names ("BlueCard", "RedSkull")."""
    held: set[str] = set()
    for key in keys_held:
        lowered = key.lower()
        held.update(colour for colour in _COLOURS if lowered.startswith(colour))
    return frozenset(held)


def distance_to_segment(
    px: float, py: float, start: tuple[float, float], end: tuple[float, float]
) -> float:
    """Shortest distance from the point (px, py) to the segment start-end."""
    (ax, ay), (bx, by) = start, end
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    along = 0.0
    if length_sq != 0:
        along = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + along * dx), py - (ay + along * dy))


def on_front_side(face: Segment, x: float, y: float) -> bool:
    """Whether a point is on the side of a line from which USE works."""
    x1, y1, x2, y2 = face
    cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
    return cross < 0  # Doom: the front side is the right of v1 -> v2


def can_use_from(faces: Iterable[Segment], x: float, y: float) -> bool:
    """Standing at x, y, on the front side of one of the lines and within USE range of it."""
    return any(
        on_front_side(f, x, y)
        and distance_to_segment(x, y, (f[0], f[1]), (f[2], f[3])) <= USE_RANGE
        for f in faces
    )
