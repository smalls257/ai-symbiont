"""Rasterise a map's walls, sectors, doors and heights onto a grid (pure).

Reads: the parsed geometry and the door sectors. Produces: plain arrays that `navgrid.WalkGrid`
wraps. Nothing here searches or routes (Shield: building the grid and walking it change for
different reasons).
"""

import math
from collections.abc import Container, Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from symbiont.act1.map_index import MapIndex
from symbiont.act1.navtypes import CELL, Segment, distance_to_segment
from symbiont.act1.wad import Linedef, MapGeometry, Sector

# wall-to-cell-centre distance below which a cell is blocked (player radius is 16)
PLAYER_CLEARANCE = 12.0
PLAYER_HEIGHT = 56  # smallest opening the player fits through
IMPASSABLE = 1  # linedef flag bit
# a door sector is judged by where it goes when used, not by its shut ceiling
OPEN_DOOR_CEILING = 10_000
FAR = 10**6
MAX_CELLS = 2_000_000
STRADDLE_CELLS = 1  # cells either side of a cell that its body overlaps
_Edge = tuple[tuple[int, int], tuple[int, int]]


@dataclass(frozen=True)
class Frame:
    """Where the grid sits on the map: origin, size, and cell <-> map-unit conversion."""

    x0: float
    y0: float
    cols: int
    rows: int

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """Grid column and row containing a map point."""
        return int((x - self.x0) // CELL), int((y - self.y0) // CELL)

    def centre(self, col: int, row: int) -> tuple[float, float]:
        """Map coordinates of a cell centre."""
        return self.x0 + (col + 0.5) * CELL, self.y0 + (row + 0.5) * CELL

    def in_bounds(self, col: int, row: int) -> bool:
        """Whether a column and row lie on the grid."""
        return 0 <= col < self.cols and 0 <= row < self.rows

    def cells_in(self, low: tuple[float, float], high: tuple[float, float]) -> Iterator[int]:
        """Indexes of the cells covering the box low..high, clipped to the grid."""
        c0, r0 = self.cell_of(*low)
        c1, r1 = self.cell_of(*high)
        for row in range(max(r0, 0), min(r1, self.rows - 1) + 1):
            for col in range(max(c0, 0), min(c1, self.cols - 1) + 1):
                yield row * self.cols + col


def build_frame(geometry: MapGeometry) -> Frame:
    """Size the grid to the map; raises ValueError over MAX_CELLS."""
    xs = [v[0] for v in geometry.vertices]
    ys = [v[1] for v in geometry.vertices]
    x0, y0 = min(xs) - CELL, min(ys) - CELL
    cols, rows = int((max(xs) - x0) // CELL) + 2, int((max(ys) - y0) // CELL) + 2
    if cols * rows > MAX_CELLS:
        raise ValueError(f"map is {cols}x{rows} cells, over the {MAX_CELLS} limit")
    return Frame(x0, y0, cols, rows)


def door_tables(
    geometry: MapGeometry, index: MapIndex
) -> tuple[dict[int, str | None], dict[int, tuple[Segment, ...]]]:
    """Door sector -> key colour, and door sector -> the lines that carry its use-special."""
    colours: dict[int, str | None] = {}
    faces: dict[int, tuple[Segment, ...]] = {}
    for door in index.doors:
        if door.sector is None:
            continue
        line = geometry.linedefs[door.line]
        (x1, y1), (x2, y2) = geometry.vertices[line.v1], geometry.vertices[line.v2]
        colours[door.sector] = door.key_colour
        faces[door.sector] = (*faces.get(door.sector, ()), (x1, y1, x2, y2))
    return colours, faces


# --- walls ------------------------------------------------------------------------------------


def _is_wall(line: Linedef) -> bool:
    return line.front_sector is None or line.back_sector is None or bool(line.flags & IMPASSABLE)


def block_walls(geometry: MapGeometry, frame: Frame) -> bytearray:
    """1 for every cell within PLAYER_CLEARANCE of a wall line."""
    blocked = bytearray(frame.cols * frame.rows)
    for line in geometry.linedefs:
        if _is_wall(line):
            _block_around(blocked, frame, geometry.vertices[line.v1], geometry.vertices[line.v2])
    return blocked


def _block_around(
    blocked: bytearray, frame: Frame, start: tuple[int, int], end: tuple[int, int]
) -> None:
    reach = PLAYER_CLEARANCE
    low = (min(start[0], end[0]) - reach, min(start[1], end[1]) - reach)
    high = (max(start[0], end[0]) + reach, max(start[1], end[1]) + reach)
    for cell in frame.cells_in(low, high):
        row, col = divmod(cell, frame.cols)
        x, y = frame.centre(col, row)
        if distance_to_segment(x, y, start, end) <= reach:
            blocked[cell] = 1


# --- sectors ----------------------------------------------------------------------------------


def _sector_edges(geometry: MapGeometry) -> dict[int, list[_Edge]]:
    edges: dict[int, list[_Edge]] = {}
    for line in geometry.linedefs:
        if line.front_sector == line.back_sector:
            continue
        ends = (geometry.vertices[line.v1], geometry.vertices[line.v2])
        for sector in (line.front_sector, line.back_sector):
            if sector is not None:
                edges.setdefault(sector, []).append(ends)
    return edges


def sector_owner(geometry: MapGeometry, frame: Frame) -> np.ndarray:
    """Sector number of each cell (-1 outside every sector), by even-odd scanlines."""
    owner = np.full((frame.rows, frame.cols), -1, dtype=np.int32)
    for sector, segments in sorted(_sector_edges(geometry).items()):
        low = min(min(a[1], b[1]) for a, b in segments)
        high = max(max(a[1], b[1]) for a, b in segments)
        first_row, last_row = frame.cell_of(0, low)[1], frame.cell_of(0, high)[1]
        for row in range(max(first_row, 0), min(last_row, frame.rows - 1) + 1):
            _fill_row(owner, frame, sector, segments, row)
    return owner


def _fill_row(
    owner: np.ndarray, frame: Frame, sector: int, segments: list[_Edge], row: int
) -> None:
    """Widen spans by half a cell so a sector thinner than a cell still owns its cells."""
    y = frame.centre(0, row)[1]
    crossings = sorted(
        a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        for a, b in segments
        if (a[1] <= y < b[1]) or (b[1] <= y < a[1])
    )
    for left, right in zip(crossings[0::2], crossings[1::2], strict=False):
        first = max(math.ceil((left - CELL / 2 - frame.x0) / CELL - 0.5), 0)
        last = min(math.floor((right + CELL / 2 - frame.x0) / CELL - 0.5), frame.cols - 1)
        owner[row, first : last + 1] = sector


# --- doors ------------------------------------------------------------------------------------


def sector_box(
    geometry: MapGeometry, sector: int
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Bounding box (low, high) of a sector's boundary lines, or None when it has none."""
    points = [
        geometry.vertices[v]
        for line in geometry.linedefs
        if sector in (line.front_sector, line.back_sector)
        for v in (line.v1, line.v2)
    ]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys)), (max(xs), max(ys))


def door_cells(
    geometry: MapGeometry, frame: Frame, blocked: bytearray, door_sectors: Iterable[int]
) -> dict[int, int]:
    """Cell -> door sector for unblocked cells in each door's bounding box (first wins)."""
    door_at: dict[int, int] = {}
    for sector in sorted(door_sectors):
        box = sector_box(geometry, sector)
        for cell in frame.cells_in(*box) if box else ():
            if not blocked[cell]:
                door_at.setdefault(cell, sector)
    return door_at


# --- heights ----------------------------------------------------------------------------------


def effective_heights(
    sectors: list[Sector], owner: np.ndarray, door_sectors: Container[int], frame: Frame
) -> tuple[np.ndarray, np.ndarray]:
    """Per cell: highest floor and lowest ceiling within STRADDLE_CELLS (the body spans them)."""
    floors = np.full(len(sectors) + 1, -FAR, dtype=np.int64)  # last slot: outside every sector
    ceilings = np.full(len(sectors) + 1, FAR, dtype=np.int64)
    for number, sector in enumerate(sectors):
        floors[number] = sector.floor
        ceilings[number] = OPEN_DOOR_CEILING if number in door_sectors else sector.ceiling
    floor, ceiling = floors[owner], ceilings[owner]  # -1 indexes the outside slot
    reach = STRADDLE_CELLS
    padded_floor = np.pad(floor, reach, constant_values=-FAR)
    padded_ceiling = np.pad(ceiling, reach, constant_values=FAR)
    best_floor, best_ceiling = floor.copy(), ceiling.copy()
    for dr in range(-reach, reach + 1):
        for dc in range(-reach, reach + 1):
            window = (
                slice(reach + dr, reach + dr + frame.rows),
                slice(reach + dc, reach + dc + frame.cols),
            )
            best_floor = np.maximum(best_floor, padded_floor[window])
            best_ceiling = np.minimum(best_ceiling, padded_ceiling[window])
    return best_floor, best_ceiling


def block_unusable_cells(
    blocked: bytearray, owner: np.ndarray, floor: np.ndarray, ceiling: np.ndarray
) -> None:
    """Block cells outside every sector or with less than PLAYER_HEIGHT of headroom."""
    unusable = (owner.ravel() < 0) | ((ceiling - floor).ravel() < PLAYER_HEIGHT)
    for cell in np.flatnonzero(unusable):
        blocked[int(cell)] = 1
