"""Which room the player is in: the map sector that holds a point (pure).

A room is a sector, the map's own unit of floor and ceiling. Episode records name rooms so the game
pain points (same room re-entered, a room re-checked) can be found from positions alone.

Violation prevented: Silent Fallback. A point inside no sector raises `RoomLookupError` instead of
reporting "room unknown", which would quietly drop re-entries from the episode log.
"""

from collections import defaultdict

from symbiont.act1.wad import MapGeometry

Edge = tuple[tuple[float, float], tuple[float, float]]


class RoomLookupError(ValueError):
    """The point is inside no sector of the map."""


class RoomFinder:
    """Point-in-sector lookup by ray parity over each sector's boundary lines."""

    def __init__(self, geometry: MapGeometry) -> None:
        edges: dict[int, list[Edge]] = defaultdict(list)
        for line in geometry.linedefs:
            if line.front_sector == line.back_sector:
                continue  # both sides in one sector: not a boundary of anything
            edge = (geometry.vertices[line.v1], geometry.vertices[line.v2])
            for sector in (line.front_sector, line.back_sector):
                if sector is not None:
                    edges[sector].append(edge)
        self._edges = dict(edges)

    def room_at(self, xy: tuple[float, float]) -> int:
        """The one sector holding `xy`. Raises RoomLookupError when none or several do."""
        holding = [sector for sector, edges in self._edges.items() if _inside(edges, xy)]
        if not holding:
            raise RoomLookupError(f"no sector holds the point ({xy[0]:g}, {xy[1]:g})")
        if len(holding) > 1:
            raise RoomLookupError(
                f"sectors {sorted(holding)} all hold the point ({xy[0]:g}, {xy[1]:g})"
            )
        return holding[0]


def _inside(edges: list[Edge], xy: tuple[float, float]) -> bool:
    """Even-odd rule: a ray to +x crosses the boundary an odd number of times from inside."""
    px, py = xy
    crossings = 0
    for (x1, y1), (x2, y2) in edges:
        if (y1 > py) == (y2 > py):
            continue
        if px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
            crossings += 1
    return crossings % 2 == 1
