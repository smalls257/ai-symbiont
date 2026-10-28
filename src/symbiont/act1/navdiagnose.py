"""Say why no route exists (pure): which lock, door face, wall, climb or ceiling stops it.

Each question is a relaxed re-run of the search, in the order that blames the most fixable cause
first: locks off (a key would help), then door faces off (the other side would help), then walls:
the nearest reachable point and what lies beyond it. A failure is never reported as a bare "no
path".
"""

import math
from collections.abc import Sequence

from symbiont.act1.navgrid import WalkGrid
from symbiont.act1.navroute import cells_to
from symbiont.act1.navsearch import DoorAwareSearch, DoorRules, SearchResult
from symbiont.act1.navtypes import Feature

BEYOND_CELLS = 3  # how far around the last reachable cell to look for the blocker


def explain_unreachable(
    search: DoorAwareSearch,
    start: int,
    targets: dict[int, int],
    rules: DoorRules,
    candidates: Sequence[Feature],
) -> str:
    """Blame the most fixable cause for a failed search made under `rules`."""
    grid = search.grid
    names = ", ".join(sorted({c.label for c in candidates}))
    unlocked = search.run(start, targets, rules.with_every_key())
    if unlocked.cell is not None:
        held = rules.held or frozenset()
        needed = " and ".join(_missing_colours(grid, unlocked.cell, unlocked.parent, held))
        return f"locked door: needs {needed} key on the way to {names}"
    any_side = search.run(start, targets, rules.from_any_side())
    if any_side.cell is not None:
        return (
            f"a door on the way to {names} can only be opened from its other side "
            "(its use-special faces away from here)"
        )
    gap, near, goal = _closest_approach(grid, any_side, candidates)
    x, y = grid.centre_of(near)
    return (
        f"no route to {names}: nearest reachable point {x:.0f},{y:.0f} is {gap:.0f} units from it; "
        f"beyond that is {_blocker_beyond(grid, near, any_side, goal)}"
    )


def _missing_colours(
    grid: WalkGrid, cell: int, parent: dict[int, int], held: frozenset[str]
) -> list[str]:
    on_route = cells_to(cell, parent)
    colors = {grid.door_colour[grid.door_at[c]] for c in on_route if c in grid.door_at}
    return sorted(color for color in colors if color is not None and color not in held)


def _closest_approach(
    grid: WalkGrid, result: SearchResult, candidates: Sequence[Feature]
) -> tuple[float, int, Feature]:
    return min(
        (
            (math.dist(grid.centre_of(cell), (f.x, f.y)), cell, f)
            for cell in result.explored
            for f in candidates
        ),
        key=lambda found: (found[0], found[1]),
    )


def _blocker_beyond(grid: WalkGrid, near: int, result: SearchResult, goal: Feature) -> str:
    """Why the unreached cells beside the last reachable one, nearest the goal, are closed."""
    row, col = divmod(near, grid.cols)
    unreached = [
        r * grid.cols + c
        for r in range(row - BEYOND_CELLS, row + BEYOND_CELLS + 1)
        for c in range(col - BEYOND_CELLS, col + BEYOND_CELLS + 1)
        if grid.frame.in_bounds(c, r) and (r * grid.cols + c) not in result.explored
    ]
    if not unreached:
        return "nothing: the map ends here"
    wall = min(unreached, key=lambda cell: math.dist(grid.centre_of(cell), (goal.x, goal.y)))
    return grid.why_blocked(near, wall)
