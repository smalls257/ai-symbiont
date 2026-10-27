"""The walkable grid of one map: where a player can stand, how high, and the doors (pure).

Walls: one-sided or impassable-flag lines, inflated by the player's clearance. Height: a cell's
effective floor is the highest floor within one cell of it (a player straddling a narrow trench
stands on the higher side); a move may rise at most STEP_UP, falling is allowed, so edges are
directed. A cell with less than PLAYER_HEIGHT of headroom, or outside every sector, is blocked. Door
sectors listed in the map index are crossable door cells that ignore headroom (shut now, open when
used); doors the index does not list read as walls, so "no route" names the blocker instead of
guessing.
"""

import math
from collections.abc import Sequence

from symbiont.act1.map_index import MapIndex
from symbiont.act1.navbuild import (
    PLAYER_HEIGHT,
    block_unusable_cells,
    block_walls,
    build_frame,
    door_cells,
    door_tables,
    effective_heights,
    sector_owner,
)
from symbiont.act1.navtypes import CELL, Feature, on_front_side
from symbiont.act1.wad import MapGeometry

STEP_UP = 24  # largest floor difference the player walks over
START_SNAP_CELLS = 4  # how far from a wall-hugging start position the nearest free cell may be
LOS_STEP = CELL / 2


class WalkGrid:
    """Walkable cells of one map, with heights and door cells."""

    def __init__(self, geometry: MapGeometry, index: MapIndex) -> None:
        self.frame = build_frame(geometry)
        self.door_colour, self.door_faces = door_tables(geometry, index)
        self.blocked = block_walls(geometry, self.frame)
        owner = sector_owner(geometry, self.frame)
        self.door_at = door_cells(geometry, self.frame, self.blocked, self.door_colour)
        floor, ceiling = effective_heights(geometry.sectors, owner, self.door_colour, self.frame)
        block_unusable_cells(self.blocked, owner, floor, ceiling)
        self._outside = (owner < 0).ravel().tolist()
        self.floor, self.ceiling = floor.ravel().tolist(), ceiling.ravel().tolist()

    @property
    def cols(self) -> int:
        """Grid width in cells."""
        return self.frame.cols

    def free(self, col: int, row: int) -> bool:
        """Whether a cell is on the grid and not blocked."""
        return self.frame.in_bounds(col, row) and not self.blocked[row * self.frame.cols + col]

    def centre_of(self, cell: int) -> tuple[float, float]:
        """Map coordinates of a cell index."""
        row, col = divmod(cell, self.frame.cols)
        return self.frame.centre(col, row)

    def start_cell(self, xy: tuple[float, float]) -> int | None:
        """The free cell nearest a position, searched a few cells out for wall-hugging starts."""
        col, row = self.frame.cell_of(*xy)
        reach = range(-START_SNAP_CELLS, START_SNAP_CELLS + 1)
        free_cells = [
            (col + dc, row + dr) for dr in reach for dc in reach if self.free(col + dc, row + dr)
        ]
        if not free_cells:
            return None
        _, cell = min(
            (math.dist(xy, self.frame.centre(c, r)), r * self.frame.cols + c) for c, r in free_cells
        )
        return cell

    def target_cells(self, candidates: Sequence[Feature]) -> dict[int, int]:
        """Cell -> index of the candidate it reaches (free, non-door, in reach, use-face side)."""
        cells: dict[int, int] = {}
        for number, feature in enumerate(candidates):
            for cell in self._cells_reaching(feature):
                cells.setdefault(cell, number)
        return cells

    def _cells_reaching(self, feature: Feature) -> list[int]:
        span = feature.reach + CELL
        low, high = (feature.x - span, feature.y - span), (feature.x + span, feature.y + span)
        reaching = []
        for cell in self.frame.cells_in(low, high):
            x, y = self.centre_of(cell)
            near = math.dist((x, y), (feature.x, feature.y)) <= feature.reach
            facing = not feature.faces or any(on_front_side(f, x, y) for f in feature.faces)
            if near and facing and not self.blocked[cell] and cell not in self.door_at:
                reaching.append(cell)
        return reaching

    def clear_line(self, origin: tuple[float, float], goal: tuple[float, float]) -> bool:
        """A straight walk from origin to goal on free, non-door cells, no step over STEP_UP."""
        steps = max(1, int(math.dist(origin, goal) / LOS_STEP))
        previous = None
        for step in range(steps + 1):
            fraction = step / steps
            col, row = self.frame.cell_of(
                origin[0] + (goal[0] - origin[0]) * fraction,
                origin[1] + (goal[1] - origin[1]) * fraction,
            )
            cell = row * self.frame.cols + col
            if not self.free(col, row) or cell in self.door_at:
                return False
            if previous is not None and self.floor[cell] - self.floor[previous] > STEP_UP:
                return False
            previous = cell
        return True

    def why_blocked(self, from_cell: int, to_cell: int) -> str:
        """In words, why a player on from_cell cannot step onto to_cell."""
        if self._outside[to_cell]:
            return "the edge of the map (no sector there)"
        headroom = self.ceiling[to_cell] - self.floor[to_cell]
        if headroom < PLAYER_HEIGHT:
            return f"only {headroom} units of headroom (a door or lift the map does not list)"
        if self.blocked[to_cell]:
            return "a wall"
        return f"a {self.floor[to_cell] - self.floor[from_cell]}-unit climb"
