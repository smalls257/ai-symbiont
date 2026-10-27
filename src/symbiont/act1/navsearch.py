"""Shortest walking route over a WalkGrid, with the door rules (pure, deterministic).

Rules beyond walls and climbs: a locked door is crossable only with its key colour held, and a shut
door is entered only from where its use-special can be pressed (USE works from a line's front side
only). The two rules can be switched off one at a time, so a failed search can be re-run to learn
which of them (or neither: plain walls) was the cause.
"""

import heapq
import math
from collections.abc import Iterator
from dataclasses import dataclass, replace

from symbiont.act1.navgrid import STEP_UP, WalkGrid
from symbiont.act1.navtypes import CELL, can_use_from

_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
_DIAGONAL = CELL * math.sqrt(2)


@dataclass(frozen=True)
class DoorRules:
    """Which doors a search may cross.

    `held` None lets every locked door through, `closed` None assumes every door is shut,
    `enforce_faces` False lets a door be entered from either side.
    """

    held: frozenset[str] | None
    closed: frozenset[int] | None
    enforce_faces: bool = True

    def with_every_key(self) -> "DoorRules":
        """The same rules with every locked door passable."""
        return replace(self, held=None)

    def from_any_side(self) -> "DoorRules":
        """The same rules with locks off and doors enterable from either side."""
        return replace(self, held=None, enforce_faces=False)


@dataclass(frozen=True)
class SearchResult:
    """Outcome of one search: the cell reached (None if none), its length and the cells explored."""

    cell: int | None  # the first target cell reached, None when none can be
    length: float
    parent: dict[int, int]
    explored: dict[int, float]  # every cell reached -> its walking distance


class DoorAwareSearch:
    """Dijkstra over the walk grid; reused across searches so door-face checks are cached."""

    def __init__(self, grid: WalkGrid) -> None:
        self._grid = grid
        self._usable: dict[tuple[int, int], bool] = {}

    @property
    def grid(self) -> WalkGrid:
        """The grid being searched."""
        return self._grid

    def run(self, start: int, targets: dict[int, int], rules: DoorRules) -> SearchResult:
        """Cheapest walk from `start` to the first of `targets` that the door rules allow."""
        walked = {start: 0.0}
        parent: dict[int, int] = {}
        heap = [(0.0, start)]
        while heap:
            length, cell = heapq.heappop(heap)
            if length > walked.get(cell, math.inf):
                continue
            if cell in targets:
                return SearchResult(cell, length, parent, walked)
            for neighbour, cost in self._moves(cell):
                if self._blocked_by_doors(cell, neighbour, rules):
                    continue
                if length + cost < walked.get(neighbour, math.inf):
                    walked[neighbour] = length + cost
                    parent[neighbour] = cell
                    heapq.heappush(heap, (length + cost, neighbour))
        return SearchResult(None, math.inf, parent, walked)

    def _blocked_by_doors(self, origin: int, cell: int, rules: DoorRules) -> bool:
        if self._locked_for(cell, rules.held):
            return True
        return rules.enforce_faces and not self._enterable(origin, cell, rules.closed)

    def _moves(self, cell: int) -> Iterator[tuple[int, float]]:
        """Neighbouring cells a player can step onto from here, with the step's length."""
        grid = self._grid
        row, col = divmod(cell, grid.cols)
        for dc, dr in _NEIGHBOURS:
            if not grid.free(col + dc, row + dr):
                continue
            if dc and dr and not (grid.free(col + dc, row) and grid.free(col, row + dr)):
                continue  # no cutting corners
            neighbour = (row + dr) * grid.cols + col + dc
            # a drop is fine, a tall step is not
            if grid.floor[neighbour] - grid.floor[cell] <= STEP_UP:
                yield neighbour, _DIAGONAL if dc and dr else CELL

    def _enterable(self, origin: int, cell: int, closed: frozenset[int] | None) -> bool:
        """Entering a shut door's cell from outside needs a use-face in reach and in front."""
        sector = self._grid.door_at.get(cell)
        if (
            sector is None
            or origin in self._grid.door_at
            or (closed is not None and sector not in closed)
        ):
            return True
        key = (origin, sector)
        if key not in self._usable:
            x, y = self._grid.centre_of(origin)
            self._usable[key] = can_use_from(self._grid.door_faces[sector], x, y)
        return self._usable[key]

    def _locked_for(self, cell: int, held: frozenset[str] | None) -> bool:
        if held is None:
            return False
        colour = self._grid.door_colour.get(self._grid.door_at.get(cell, -1))
        return colour is not None and colour not in held
