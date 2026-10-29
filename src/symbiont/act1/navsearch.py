"""Shortest walking route over a WalkGrid, with the door rules (pure, deterministic).

Rules beyond walls and climbs: a locked door is crossable only with its key color held, and a shut
door is entered only from where its use-special can be pressed (USE works from a line's front side
only). The two rules can be switched off one at a time, so a failed search can be re-run to learn
which of them (or neither: plain walls) was the cause.
"""

import heapq
import math
from dataclasses import dataclass, replace

from symbiont.act1.navgrid import STEP_UP, WalkGrid
from symbiont.act1.navtypes import CELL, can_use_from

_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
_DIAGONAL = CELL * math.sqrt(2)
TELEPORT_COST = 4 * CELL  # walking onto the pad and the fog; keeps teleport loops from looking free


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
        """Search over `grid`; flat-index offsets are safe because its border cells are blocked."""
        self._grid = grid
        self._usable: dict[tuple[int, int], bool] = {}
        cols = grid.cols  # flat-index offsets: the grid's border cells are blocked, so none wrap
        self._orthogonal = tuple((off, float(CELL)) for off in (1, -1, cols, -cols))
        self._diagonal = tuple(
            (dc + dr * cols, dc, dr * cols, _DIAGONAL) for dc in (1, -1) for dr in (1, -1)
        )

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
            for neighbor, cost in self.steps(cell, rules):
                if length + cost < walked.get(neighbor, math.inf):
                    walked[neighbor] = length + cost
                    parent[neighbor] = cell
                    heapq.heappush(heap, (length + cost, neighbor))
        return SearchResult(None, math.inf, parent, walked)

    def steps(self, cell: int, rules: DoorRules) -> list[tuple[int, float]]:
        """Cells a player can step onto from `cell` under the door rules, with the step's length.

        A drop is fine, a tall step is not, and a diagonal may not cut a corner.
        """
        grid = self._grid
        blocked, floor_in, doors = grid.blocked, grid.floor_in, grid.door_at
        reach = grid.floor[cell] + STEP_UP
        found: list[tuple[int, float]] = []
        for offset, cost in self._orthogonal:
            onto = cell + offset
            walkable = not blocked[onto] and floor_in[onto] <= reach
            if walkable and self._may_enter(cell, onto, rules, doors):
                found.append((onto, cost))
        for offset, across, down, cost in self._diagonal:
            onto = cell + offset
            if blocked[onto] or blocked[cell + across] or blocked[cell + down]:
                continue
            if floor_in[onto] <= reach and self._may_enter(cell, onto, rules, doors):
                found.append((onto, cost))
        found.extend((landing, TELEPORT_COST) for landing in grid.landing_cells(cell))
        return found

    def _may_enter(self, origin: int, cell: int, rules: DoorRules, doors: dict[int, int]) -> bool:
        """Whether the door rules let a walker step from `origin` onto `cell`."""
        if cell not in doors:
            return True
        if self._locked_for(cell, rules.held):
            return False
        return not rules.enforce_faces or self._enterable(origin, cell, rules.closed)

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
        """Whether `cell` is in a keyed door whose color is not held (None: every key is held)."""
        if held is None:
            return False
        color = self._grid.door_colour.get(self._grid.door_at.get(cell, -1))
        return color is not None and color not in held
