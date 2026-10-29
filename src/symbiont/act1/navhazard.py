"""Hazards in a planned route: lines it crosses by accident, and doors that shut behind it (pure).

The planner presses switches on purpose; walkover lines are also crossed without meaning to. A
line that closes a door or lowers a ceiling can take back a passage the route needs later, and a
door that opens and closes by itself is only open for a while. Either makes the route fragile:
it is returned with the reasons, never as a plain success.
"""

from symbiont.act1.navbuild import PLAYER_HEIGHT, SectorState
from symbiont.act1.navgrid import WalkGrid
from symbiont.act1.navmech import Mechanism, apply_mechanism
from symbiont.act1.navplan import Leg, Planned
from symbiont.act1.navspecials import Effect, Trigger
from symbiont.act1.navtypes import CELL, Segment
from symbiont.act1.wad import MapGeometry

HAZARD_EFFECTS = frozenset({Effect.CLOSE_DOOR, Effect.LOWER_CEILING})
JUMP_CELLS = 2  # consecutive path cells farther apart than this are a teleport, not a step


def audit_route(
    geometry: MapGeometry, mechanisms: tuple[Mechanism, ...], planned: Planned
) -> tuple[str, ...]:
    """Reasons the route is fragile; empty when none is found."""
    lines = [
        m
        for m in mechanisms
        if m.special.trigger == Trigger.WALK and m.special.effect in HAZARD_EFFECTS
    ]
    reasons: list[str] = []
    running = list(planned.legs[0].grid.states)
    for number, leg in enumerate(planned.legs):
        later = planned.legs[number + 1 :]
        reasons.extend(_crossings(geometry, lines, leg, later, running))
        if leg.firing is not None:
            running = apply_mechanism(geometry, running, leg.firing.mechanism)
    return tuple(reasons)


def _crossings(
    geometry: MapGeometry,
    lines: list[Mechanism],
    leg: Leg,
    later: list[Leg],
    running: list[SectorState],
) -> list[str]:
    """Hazard lines the leg's path crosses whose effect takes away a sector still to be walked."""
    found: list[str] = []
    grid = leg.grid
    for at in range(len(leg.cells) - 1):
        start, end = grid.centre_of(leg.cells[at]), grid.centre_of(leg.cells[at + 1])
        if _gap(start, end) > JUMP_CELLS * CELL:
            continue
        for mech in lines:
            if not _crosses(start, end, mech.segment):
                continue
            after = apply_mechanism(geometry, running, mech)
            lost = _lost(running, after, mech) & _still_to_walk(grid, leg.cells[at + 1 :], later)
            if lost:
                found.append(_reason(mech, sorted(lost)))
            running[:] = after
    return found


def _gap(start: tuple[float, float], end: tuple[float, float]) -> float:
    return max(abs(start[0] - end[0]), abs(start[1] - end[1]))


def _lost(before: list[SectorState], after: list[SectorState], mech: Mechanism) -> set[int]:
    """Sectors of the mechanism that were passable and no longer are."""

    def passable(state: SectorState) -> bool:
        return state.ceiling - state.floor_out >= PLAYER_HEIGHT

    return {s for s in mech.sectors if passable(before[s]) and not passable(after[s])}


def _still_to_walk(grid: WalkGrid, rest: list[int], later: list[Leg]) -> set[int]:
    sectors = grid.sectors_in(rest) if rest else set()
    for leg in later:
        sectors |= leg.grid.sectors_in(leg.cells)
    return sectors


def _reason(mech: Mechanism, sectors: list[int]) -> str:
    return (
        f"crosses line {mech.line} (special {mech.number}) which shuts sector "
        f"{', '.join(map(str, sectors))} that the route walks through afterwards"
    )


def _side(point: tuple[float, float], line: Segment) -> float:
    """Positive on one side of the line through the segment, negative on the other."""
    x1, y1, x2, y2 = line
    return (x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1)


def _crosses(start: tuple[float, float], end: tuple[float, float], line: Segment) -> bool:
    """Whether the step start -> end properly crosses the line segment."""
    x1, y1, x2, y2 = line
    step = (*start, *end)
    return (
        _side(start, line) * _side(end, line) < 0
        and _side((x1, y1), step) * _side((x2, y2), step) < 0
    )
