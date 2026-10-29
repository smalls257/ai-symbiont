"""The walkable grid of one map: where a player can stand, how high, and the doors (pure).

Walls are inflated by the player's clearance; a move may rise at most STEP_UP and falling is
allowed, so edges are directed. A cell with less than PLAYER_HEIGHT of headroom is blocked. Listed
door sectors are crossable; unlisted doors read as walls, so "no route" names the blocker.
"""

import copy
import math
from collections.abc import Iterable, Sequence

import numpy as np

from symbiont.act1.map_index import MapIndex
from symbiont.act1.navbuild import (
    PLAYER_HEIGHT,
    SectorState,
    base_states,
    block_scenery,
    block_unusable_cells,
    block_walls,
    build_frame,
    door_cells,
    door_tables,
    effective_heights,
    sector_owner,
)
from symbiont.act1.navmech import Mechanism
from symbiont.act1.navtele import teleport_edges
from symbiont.act1.navtypes import CELL, PICKUP_ABOVE, PICKUP_BELOW, Feature, on_front_side
from symbiont.act1.wad import MapGeometry

STEP_UP = 24  # largest floor difference the player walks over
START_SNAP_CELLS = 4  # how far from a wall-hugging start position the nearest free cell may be
LOS_STEP = CELL / 2
RING_CELLS = 2  # cells around a sector that its height can change: its own and the straddlers


class WalkGrid:
    """Walkable cells of one map, with heights and door cells."""

    def __init__(
        self, geometry: MapGeometry, index: MapIndex, mechanisms: tuple[Mechanism, ...] = ()
    ) -> None:
        """Rasterize the map once; the sector-height-dependent parts are settled per world."""
        self.frame = build_frame(geometry)
        self.door_colour, self.door_faces = door_tables(geometry, index)
        walls = block_walls(geometry, self.frame)
        block_scenery(geometry, self.frame, walls)
        self._owner = sector_owner(geometry, self.frame)
        self.door_at = door_cells(geometry, self.frame, walls, self.door_colour)
        self._walls = bytes(walls)
        self._outside = (self._owner < 0).ravel().tolist()
        self.base_states = base_states(geometry.sectors, self.door_colour)
        self._settle(self.base_states)
        self._rings: dict[int, list[int]] = {}
        self.teleports, self.orphan_teleports = teleport_edges(
            geometry, mechanisms, self.frame, self._owner
        )

    def in_world(self, states: list[SectorState]) -> "WalkGrid":
        """The same map with its sectors at `states` (after a switch, lift or door has run)."""
        twin = copy.copy(self)
        twin._settle(states)
        return twin

    def _settle(self, states: list[SectorState]) -> None:
        """Take the heights in `states`: each cell's floors, headroom and blocked flag."""
        self.states = states
        floor_in, floor_out, ceiling = effective_heights(states, self._owner)
        self.blocked = bytearray(self._walls)
        block_unusable_cells(self.blocked, self._owner, floor_out, ceiling)
        self._landings: dict[int, list[int]] = {}
        self.floor_in = floor_in.ravel().tolist()
        self.floor = floor_out.ravel().tolist()
        self.ceiling = ceiling.ravel().tolist()

    def ring_of_sector(self, sector: int) -> list[int]:
        """The cells of a sector and the cells touching them (where a change in it shows)."""
        if sector not in self._rings:
            own = np.flatnonzero(self._owner.ravel() == sector)
            spread = range(-RING_CELLS, RING_CELLS + 1)  # a closed sector blocks its straddlers too
            reach = np.array([dr * self.cols + dc for dr in spread for dc in spread])
            around = np.unique((own[:, None] + reach[None, :]).ravel())
            self._rings[sector] = around[(around >= 0) & (around < self._owner.size)].tolist()
        return self._rings[sector]

    def landing_cells(self, cell: int) -> list[int]:
        """Free cells a teleport line near `cell` lands on (cached per world)."""
        if cell not in self.teleports:
            return []
        if cell not in self._landings:
            landings = (self.start_cell(edge.landing) for edge in self.teleports[cell])
            self._landings[cell] = [found for found in landings if found is not None]
        return self._landings[cell]

    def sectors_in(self, cells: Iterable[int]) -> set[int]:
        """The sectors that own any of the cells (-1, outside every sector, left out)."""
        owners = self._owner.ravel()[np.fromiter(cells, dtype=np.int64)]
        return {int(sector) for sector in np.unique(owners) if sector >= 0}

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
        return self.frame.center(col, row)

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
            (math.dist(xy, self.frame.center(c, r)), r * self.frame.cols + c) for c, r in free_cells
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
        """Free, non-door cells near a feature, on its use-face side and at a pickable height."""
        span = feature.reach + CELL
        low, high = (feature.x - span, feature.y - span), (feature.x + span, feature.y + span)
        reaching = []
        for cell in self.frame.cells_in(low, high):
            x, y = self.centre_of(cell)
            near = math.dist((x, y), (feature.x, feature.y)) <= feature.reach
            facing = not feature.faces or any(on_front_side(f, x, y) for f in feature.faces)
            touching = feature.item_sector is None or self._touches(cell, feature.item_sector)
            if near and facing and touching and not self.blocked[cell] and cell not in self.door_at:
                reaching.append(cell)
        return reaching

    def _touches(self, cell: int, item_sector: int) -> bool:
        """Whether standing on the cell's own floor, an item on `item_sector` can be picked up."""
        floor = self.states[int(self._owner.flat[cell])].floor_out
        level = self.states[item_sector].floor_out
        return level - PICKUP_BELOW <= floor <= level + PICKUP_ABOVE

    def sector_at(self, x: float, y: float) -> int | None:
        """The sector at a map point, or None outside every sector."""
        col, row = self.frame.cell_of(x, y)
        if not self.frame.in_bounds(col, row) or self._owner[row, col] < 0:
            return None
        return int(self._owner[row, col])

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
