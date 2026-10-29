"""Teleporter edges of the walk grid (pure): crossing a teleport line lands on its destination.

A teleport line whose destination thing cannot be found is left out and counted by the caller,
never joined to a guessed spot. Vanilla teleports only on a front-to-back crossing, so approach
cells lie on the front side of the line.
"""

import math
from dataclasses import dataclass

import numpy as np

from symbiont.act1.navbuild import Frame
from symbiont.act1.navmech import Mechanism
from symbiont.act1.navspecials import Effect
from symbiont.act1.navtypes import Segment, distance_to_segment, on_front_side
from symbiont.act1.wad import MapGeometry

TELEPORT_DESTINATION = 14  # THINGS type of the teleport landing
APPROACH_UNITS = 20.0  # approach cells lie this close to the line, in front of it
THROUGH_UNITS = 28.0  # a walker aims this far past the line so the crossing is certain


@dataclass(frozen=True)
class TeleportEdge:
    """Walk from an approach cell to `through` (just past the line) and arrive at `landing`."""

    through: tuple[float, float]
    landing: tuple[float, float]


def landing_of(
    geometry: MapGeometry, frame: Frame, owner: np.ndarray, tag_sectors: set[int]
) -> tuple[float, float] | None:
    """Where the first destination thing in a sector with the tag stands, or None."""
    for thing in geometry.things:
        if thing.type != TELEPORT_DESTINATION:
            continue
        col, row = frame.cell_of(thing.x, thing.y)
        if frame.in_bounds(col, row) and int(owner[row, col]) in tag_sectors:
            return (float(thing.x), float(thing.y))
    return None


def through_point(segment: Segment, x: float, y: float) -> tuple[float, float]:
    """The point THROUGH_UNITS past the line, straight across from (x, y)."""
    x1, y1, x2, y2 = segment
    length = math.hypot(x2 - x1, y2 - y1)
    nx, ny = (y2 - y1) / length, -(x2 - x1) / length  # points to the front side (right of v1->v2)
    along = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / length**2
    along = max(0.0, min(1.0, along))
    foot = (x1 + along * (x2 - x1), y1 + along * (y2 - y1))
    side = 1.0 if on_front_side(segment, x, y) else -1.0
    return (foot[0] - side * nx * THROUGH_UNITS, foot[1] - side * ny * THROUGH_UNITS)


def teleport_edges(
    geometry: MapGeometry,
    mechanisms: tuple[Mechanism, ...],
    frame: Frame,
    owner: np.ndarray,
) -> tuple[dict[int, list[TeleportEdge]], list[int]]:
    """Cell -> edges leaving it, and the numbers of teleport lines with no destination thing."""
    edges: dict[int, list[TeleportEdge]] = {}
    orphans: list[int] = []
    for mech in mechanisms:
        if mech.special.effect != Effect.TELEPORT:
            continue
        landing = landing_of(geometry, frame, owner, set(mech.sectors))
        if landing is None:
            orphans.append(mech.line)
            continue
        x1, y1, x2, y2 = mech.segment
        mid = ((x1 + x2) / 2, (y1 + y2) / 2)
        span = max(abs(x2 - x1), abs(y2 - y1)) / 2 + APPROACH_UNITS
        for cell in frame.cells_in((mid[0] - span, mid[1] - span), (mid[0] + span, mid[1] + span)):
            row, col = divmod(cell, frame.cols)
            x, y = frame.center(col, row)
            near = distance_to_segment(x, y, (x1, y1), (x2, y2)) <= APPROACH_UNITS
            if near and on_front_side(mech.segment, x, y):
                through = through_point(mech.segment, x, y)
                edges.setdefault(cell, []).append(TeleportEdge(through, landing))
    return edges, orphans
