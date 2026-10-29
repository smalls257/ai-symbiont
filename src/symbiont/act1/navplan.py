"""Plan a route that sets off switches, lifts and remote doors on the way to a goal (pure).

A walk that only exists after a switch is pressed says so as an action waypoint in its route; a
plan that cannot find such a switch returns the stuck search for the diagnosis, never a route that
would stop at a wall. Each firing is simulated on a copy of the grid (`apply_mechanism`) and the
search runs again, so each leg is a plain walk in one world.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from symbiont.act1.navbuild import SectorState
from symbiont.act1.navgrid import WalkGrid
from symbiont.act1.navmech import FIRABLE_EFFECTS, Mechanism, apply_mechanism
from symbiont.act1.navroute import cells_to, ending_on, waypoints_for
from symbiont.act1.navsearch import DoorAwareSearch, DoorRules, SearchResult
from symbiont.act1.navspecials import Effect, Trigger
from symbiont.act1.navtele import TeleportEdge, through_point
from symbiont.act1.navtypes import (
    Action,
    Feature,
    Route,
    Waypoint,
    can_use_from,
    distance_to_segment,
)
from symbiont.act1.wad import MapGeometry

NEAR_SECTOR_STEPS = 2  # how many sectors away from the walked region a mechanism may act
MAX_FIRINGS = 12  # most switches one plan may press; a map needing more is reported, not guessed
SWITCH_REACH = 40.0  # a switch is pressed from this close to its line
WALKOVER_REACH = 16.0  # a walkover line is crossed from this close to it


@dataclass(frozen=True)
class Firing:
    """A mechanism set off at the end of a leg."""

    mechanism: Mechanism
    cell: int  # where the walker stands to set it off
    through: tuple[float, float] | None  # walkover: the point to walk to, across the line
    # a timed door: the sectors it opens and the states they go back to when it shuts again
    shuts_again: tuple[tuple[int, SectorState], ...] = ()


@dataclass(frozen=True)
class Leg:
    """A plain walk in one world, ending in a firing (or at the goal when `firing` is None)."""

    grid: WalkGrid
    cells: list[int]
    length: float
    firing: Firing | None


@dataclass(frozen=True)
class Planned:
    """The legs from the start to a goal cell."""

    legs: list[Leg]
    goal: Feature  # the candidate the last leg reaches


@dataclass(frozen=True)
class Stage:
    """A world, where the walker stands in it, and the search from there.

    When a plan fails this is the last stage: the world after every useful firing, with the search
    that still could not reach the goal.
    """

    grid: WalkGrid
    start: int
    result: SearchResult


@dataclass(frozen=True)
class _Goal:
    """What a search is for: the features that would do, and the door rules it runs under."""

    candidates: Sequence[Feature]
    rules: DoorRules


def _sector_neighbors(geometry: MapGeometry) -> dict[int, set[int]]:
    """Sectors that share a two-sided line, both ways."""
    found: dict[int, set[int]] = {}
    for line in geometry.linedefs:
        if line.front_sector is None or line.back_sector is None:
            continue
        found.setdefault(line.front_sector, set()).add(line.back_sector)
        found.setdefault(line.back_sector, set()).add(line.front_sector)
    return found


class RoutePlanner:
    """Finds a walk to a goal, pressing the switches and crossing the lines it needs."""

    def __init__(
        self, geometry: MapGeometry, grid: WalkGrid, mechanisms: Iterable[Mechanism]
    ) -> None:
        """Hold the map, its grid and the mechanisms the planner may press."""
        self._geometry, self._grid = geometry, grid
        self._mechanisms = tuple(m for m in mechanisms if m.special.effect in FIRABLE_EFFECTS)
        self._neighbors = _sector_neighbors(geometry)

    def plan(
        self,
        start: int,
        candidates: Sequence[Feature],
        rules: DoorRules,
        states: list[SectorState] | None = None,
    ) -> Planned | Stage:
        """Legs to the nearest of `candidates`, or the last Stage. `states`: the world right now."""
        grid = self._grid if states is None else self._grid.in_world(states)
        goal = _Goal(candidates, rules)
        result = DoorAwareSearch(grid).run(start, grid.target_cells(candidates), rules)
        legs: list[Leg] = []
        used: set[int] = set()
        closing: tuple[tuple[int, SectorState], ...] = ()
        for _ in range(MAX_FIRINGS + 1):
            if result.cell is not None:
                legs.append(Leg(grid, cells_to(result.cell, result.parent), result.length, None))
                reached = candidates[grid.target_cells(candidates)[result.cell]]
                return Planned(legs, reached)
            picked = self._choose(Stage(grid, start, result), goal, (used, closing))
            if picked is None:
                break
            firing, stage = picked
            cells = cells_to(firing.cell, result.parent)
            legs.append(Leg(grid, cells, result.explored[firing.cell], firing))
            used.add(firing.mechanism.line)
            closing = firing.shuts_again
            grid, start, result = stage.grid, stage.start, stage.result
        return Stage(grid, start, result)

    # --- choosing what to press next --------------------------------------------------------

    def _choose(
        self, stuck: Stage, goal: _Goal, past: tuple[set[int], tuple[tuple[int, SectorState], ...]]
    ) -> tuple[Firing, Stage] | None:
        """The nearest mechanism whose firing frees the walker to go further, and the new stage.

        `past` is the lines already used and the doors the last firing left to shut again: they
        have shut by the time the next switch is pressed, and a one-shot cannot reopen them.
        """
        used, closing = past
        grid, result = stuck.grid, stuck.result
        options = []
        for mech in self._relevant(grid, result, goal.rules, used):
            firing = _approach(grid, mech, result.explored)
            if firing is not None:
                options.append((result.explored[firing.cell], firing))
        shut = list(grid.states)
        for sector, state in closing:
            shut[sector] = state
        for _, firing in sorted(options, key=lambda option: (option[0], option[1].mechanism.line)):
            after = apply_mechanism(self._geometry, shut, firing.mechanism)
            if after == shut:
                continue
            world = grid.in_world(after)
            began = _cell_after(world, firing)
            if began is None or not _opens_frontier(
                world, firing.mechanism, result.explored, goal.rules
            ):
                continue
            firing = _remembering_the_close(firing, shut)
            targets = world.target_cells(goal.candidates)
            outcome = DoorAwareSearch(world).run(began, targets, goal.rules)
            if outcome.cell is not None or len(outcome.explored) > len(result.explored):
                return firing, Stage(world, began, outcome)
        return None

    def _relevant(
        self, grid: WalkGrid, result: SearchResult, rules: DoorRules, used: set[int]
    ) -> list[Mechanism]:
        """Mechanisms not yet used, whose key is held, acting on or beside the walked region."""
        region = grid.sectors_in(result.explored)
        held = rules.held
        found = []
        for mech in self._mechanisms:
            key = mech.special.key
            if mech.line in used or (key is not None and held is not None and key not in held):
                continue
            if self._near_region(mech, region):
                found.append(mech)
        return found

    def _near_region(self, mech: Mechanism, region: set[int]) -> bool:
        """Whether its sectors, or sectors two steps from them, are among the walked ones.

        Two steps, because a closed door blocks the cells beside it as well, so the walked region
        can stop a sector short of a door it needs opened.
        """
        beside = set(mech.sectors)
        for _ in range(NEAR_SECTOR_STEPS):
            beside = beside.union(*(self._neighbors.get(s, ()) for s in beside))
        return bool(beside & region)


def _opens_frontier(
    world: WalkGrid, mech: Mechanism, explored: dict[int, float], rules: DoorRules
) -> bool:
    """Whether, in the changed world, a walked cell can step onto a cell not reached before.

    Only cells beside the mechanism's sectors are tried: a firing that opens nothing there is not
    worth a full search.
    """
    search = DoorAwareSearch(world)
    for sector in mech.sectors:
        for cell in world.ring_of_sector(sector):
            if cell in explored and any(n not in explored for n, _ in search.steps(cell, rules)):
                return True
    return False


# --- where to stand to set a mechanism off ------------------------------------------------------


def _remembering_the_close(firing: Firing, before: list[SectorState]) -> Firing:
    """A timed door's firing, tagged with the states its sectors return to."""
    if firing.mechanism.special.effect != Effect.OPEN_DOOR_TIMED:
        return firing
    return replace(firing, shuts_again=tuple((s, before[s]) for s in firing.mechanism.sectors))


def _cell_after(world: WalkGrid, firing: Firing) -> int | None:
    """The cell the walker is on once the mechanism has run."""
    if firing.through is None:
        return firing.cell
    col, row = world.frame.cell_of(*firing.through)
    return row * world.cols + col if world.free(col, row) else None


def _approach(grid: WalkGrid, mech: Mechanism, explored: dict[int, float]) -> Firing | None:
    """The nearest walked cell from which the mechanism can be set off, with the way across."""
    use = mech.special.trigger == Trigger.USE
    if not use and mech.back_sector is None:
        return None  # a one-sided line cannot be crossed
    best: Firing | None = None
    for cell in _cells_near(grid, mech, explored, SWITCH_REACH if use else WALKOVER_REACH):
        if best is not None and explored[cell] >= explored[best.cell]:
            continue
        x, y = grid.centre_of(cell)
        if use and not can_use_from([mech.segment], x, y):
            continue
        through = None if use else through_point(mech.segment, x, y)
        if through is not None and not grid.clear_line((x, y), through):
            continue  # the walker must really be able to walk across the line
        best = Firing(mech, cell, through)
    return best


def _cells_near(
    grid: WalkGrid, mech: Mechanism, explored: dict[int, float], reach: float
) -> list[int]:
    """Walked, non-door cells within `reach` of the mechanism's line."""
    x1, y1, x2, y2 = mech.segment
    low = (min(x1, x2) - reach, min(y1, y2) - reach)
    high = (max(x1, x2) + reach, max(y1, y2) + reach)
    return [
        cell
        for cell in grid.frame.cells_in(low, high)
        if cell in explored
        and cell not in grid.door_at
        and distance_to_segment(*grid.centre_of(cell), (x1, y1), (x2, y2)) <= reach
    ]


def keys_needed(planned: Planned, held: frozenset[str] | None) -> list[str]:
    """Key colors the plan opens a door or presses a switch with, that the walker does not hold."""
    colors: set[str | None] = set()
    for leg in planned.legs:
        grid = leg.grid
        colors.update(grid.door_colour.get(grid.door_at.get(cell, -1)) for cell in leg.cells)
        if leg.firing is not None:
            colors.add(leg.firing.mechanism.special.key)
    return sorted(c for c in colors if c is not None and c not in (held or ()))


# --- from legs to a route -----------------------------------------------------------------------


def route_from_plan(planned: Planned, goal: Feature) -> Route:
    """Waypoints, length and door count for a plan, with an action waypoint at each firing."""
    waypoints: list[Waypoint] = []
    doors = 0
    for leg in planned.legs:
        leg_points, leg_doors = _leg_waypoints(leg)
        waypoints.extend(leg_points)
        doors += leg_doors
        if leg.firing is not None:
            waypoints.extend(_firing_waypoints(leg.grid, leg.firing))
    last = planned.legs[-1]
    if goal.kind in ("key", "object"):
        waypoints = ending_on(last.grid, goal, waypoints, last.cells[-1])
    return Route(tuple(waypoints), sum(leg.length for leg in planned.legs), doors)


def _leg_waypoints(leg: Leg) -> tuple[list[Waypoint], int]:
    """Waypoints for a leg's cells, with a crossing waypoint wherever a teleport jumps."""
    grid = leg.grid
    waypoints: list[Waypoint] = []
    doors = 0
    for part in _split_at_jumps(grid, leg.cells):
        points, part_doors = waypoints_for(grid, part.cells)
        waypoints.extend(points)
        doors += part_doors
        if part.jump is not None:
            waypoints.append(Waypoint(*part.jump.through, lands_at=part.jump.landing))
    return waypoints, doors


@dataclass(frozen=True)
class _Part:
    cells: list[int]
    jump: TeleportEdge | None


def _split_at_jumps(grid: WalkGrid, cells: list[int]) -> list[_Part]:
    """Cut a path into walks at each teleport jump."""
    parts: list[_Part] = []
    begin = 0
    for at in range(len(cells) - 1):
        edge = _teleport_between(grid, cells[at], cells[at + 1])
        if edge is not None:
            parts.append(_Part(cells[begin : at + 1], edge))
            begin = at + 1
    parts.append(_Part(cells[begin:], None))
    return parts


def _teleport_between(grid: WalkGrid, origin: int, cell: int) -> TeleportEdge | None:
    """The teleport edge that joins two consecutive cells of a path, if they are not neighbors."""
    row, col = divmod(origin, grid.cols)
    row2, col2 = divmod(cell, grid.cols)
    if abs(row - row2) <= 1 and abs(col - col2) <= 1:
        return None
    for edge in grid.teleports.get(origin, ()):
        if grid.start_cell(edge.landing) == cell:
            return edge
    raise ValueError(f"cells {origin} and {cell} are joined by no walk and no teleport")


def _firing_waypoints(grid: WalkGrid, firing: Firing) -> list[Waypoint]:
    """The action at the end of a leg: press the switch, or walk across the line."""
    x, y = grid.centre_of(firing.cell)
    x1, y1, x2, y2 = firing.mechanism.segment
    if firing.through is None:
        return [Waypoint(x, y, action=Action.PRESS_SWITCH, aim=((x1 + x2) / 2, (y1 + y2) / 2))]
    return [Waypoint(x, y), Waypoint(*firing.through)]
