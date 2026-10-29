"""Turn a search result into waypoints a mover can follow (pure).

Cells are grouped into runs of plain floor and runs inside a door. Plain runs are thinned to the
points that keep a clear straight walk; the last waypoint before a door carries the door sector, so
the mover knows to open it. Pickups end on the item itself when the floor is clear all the way.
"""

from symbiont.act1.navgrid import WalkGrid
from symbiont.act1.navsearch import SearchResult
from symbiont.act1.navtypes import Feature, Route, Waypoint


def cells_to(cell: int, parent: dict[int, int]) -> list[int]:
    """Cells from the search start to `cell`, following parent links."""
    cells = [cell]
    while cells[-1] in parent:
        cells.append(parent[cells[-1]])
    cells.reverse()
    return cells


def build_route(grid: WalkGrid, result: SearchResult, goal: Feature) -> Route:
    """Waypoints, length and door count for a successful search."""
    assert result.cell is not None
    cells = cells_to(result.cell, result.parent)
    waypoints, doors = waypoints_for(grid, cells)
    if goal.kind in ("key", "object"):
        waypoints = ending_on(grid, goal, waypoints, cells[-1])
    return Route(tuple(waypoints), result.length, doors)


def waypoints_for(grid: WalkGrid, cells: list[int]) -> tuple[list[Waypoint], int]:
    """Thin a cell path to waypoints and count the doors crossed."""
    runs = _runs(grid, cells)
    waypoints: list[Waypoint] = []
    doors = 0
    for number, (sector, run) in enumerate(runs):
        if sector is not None:
            doors += 1
            _flag_door(grid, waypoints, cells[0], sector)
            continue
        points = _simplify(grid, run)
        if number == 0 and not (len(runs) > 1 and len(run) == 1):
            points = points[1:]  # already standing on the first cell
        waypoints.extend(Waypoint(*grid.centre_of(c)) for c in points)
    return waypoints, doors


def _runs(grid: WalkGrid, cells: list[int]) -> list[tuple[int | None, list[int]]]:
    """Group path cells into runs of plain floor and runs inside one door sector."""
    runs: list[tuple[int | None, list[int]]] = []
    for cell in cells:
        sector = grid.door_at.get(cell)
        if runs and runs[-1][0] == sector:
            runs[-1][1].append(cell)
        else:
            runs.append((sector, [cell]))
    return runs


def _flag_door(grid: WalkGrid, waypoints: list[Waypoint], first_cell: int, sector: int) -> None:
    """Mark the point before a door; a path that starts inside the door flags its own start."""
    at_door = waypoints[-1] if waypoints else Waypoint(*grid.centre_of(first_cell))
    waypoints[-1:] = [Waypoint(at_door.x, at_door.y, sector)]


def _simplify(grid: WalkGrid, run: list[int]) -> list[int]:
    """Keep the first cell and then the farthest cell in clear line of sight each time."""
    kept = [run[0]]
    at = 0
    while at < len(run) - 1:
        reach = len(run) - 1
        while reach > at + 1 and not grid.clear_line(
            grid.centre_of(run[at]), grid.centre_of(run[reach])
        ):
            reach -= 1
        kept.append(run[reach])
        at = reach
    return kept


def ending_on(
    grid: WalkGrid, goal: Feature, waypoints: list[Waypoint], last_cell: int
) -> list[Waypoint]:
    """End a pickup route on the item itself when the floor is clear all the way to it."""
    here = (waypoints[-1].x, waypoints[-1].y) if waypoints else grid.centre_of(last_cell)
    if grid.clear_line(here, (goal.x, goal.y)):
        return [*waypoints, Waypoint(goal.x, goal.y)]
    return waypoints
