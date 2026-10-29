"""Mechanisms: switches, walkover lines and teleporters that change what a route can cross (pure).

Every linedef special is looked up (an unlisted number raises) and only the modeled ones become
`Mechanism`s. What a mechanism does to the sectors it is tagged to is `apply_mechanism`, a function
from sector states to sector states; the planner calls it on a copy, never on the live grid.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from symbiont.act1.navbuild import OPEN_DOOR_CEILING, PLAYER_HEIGHT, SectorState
from symbiont.act1.navspecials import Effect, Special, Trigger, special_named
from symbiont.act1.navtypes import Segment
from symbiont.act1.wad import MapGeometry

# the floor stops 8 units short of the lowest neighboring ceiling when it would otherwise crush
CRUSH_MARGIN = 8
CRUSHING_RAISERS = frozenset({55, 56, 65, 94})
_ROUTED_EFFECTS = frozenset(
    {
        Effect.OPEN_DOOR,
        Effect.LIFT,
        Effect.LOWER_FLOOR_LOWEST,
        Effect.LOWER_FLOOR_HIGHEST,
        Effect.RAISE_FLOOR_NEXT,
        Effect.RAISE_FLOOR_CEILING,
        Effect.RAISE_FLOOR_BY,
        Effect.TELEPORT,
    }
)
_PLAYER_TRIGGERS = frozenset({Trigger.USE, Trigger.WALK})


@dataclass(frozen=True)
class Mechanism:
    """A linedef a player can set off, and the sectors carrying its tag."""

    line: int
    number: int  # the linedef special
    special: Special
    tag: int
    sectors: tuple[int, ...]
    segment: Segment  # v1 -> v2; the front side is to the right of it
    front_sector: int | None
    back_sector: int | None


def build_mechanisms(geometry: MapGeometry) -> tuple[Mechanism, ...]:
    """Every modeled, tagged special a player can set off.

    Raises UnknownSpecialError on any linedef special the table does not list, so an unmodeled
    kind is named rather than walled off.
    """
    found = []
    for number, line in enumerate(geometry.linedefs):
        if not line.special:
            continue
        special = special_named(line.special)
        sectors = tuple(n for n, s in enumerate(geometry.sectors) if line.tag and s.tag == line.tag)
        if special.effect not in _ROUTED_EFFECTS or special.trigger not in _PLAYER_TRIGGERS:
            continue
        if not sectors:
            continue
        (x1, y1), (x2, y2) = geometry.vertices[line.v1], geometry.vertices[line.v2]
        found.append(
            Mechanism(
                number,
                line.special,
                special,
                line.tag,
                sectors,
                (x1, y1, x2, y2),
                line.front_sector,
                line.back_sector,
            )
        )
    return tuple(found)


def unmodeled_notes(geometry: MapGeometry) -> dict[str, int]:
    """For each reason a special is not followed by the planner, how many lines carry one."""
    counts: dict[str, int] = {}
    for line in geometry.linedefs:
        if not line.special:
            continue
        special = special_named(line.special)
        if special.effect == Effect.UNMODELED or special.trigger == Trigger.SHOOT:
            note = special.note or "triggered by shooting"
            counts[note] = counts.get(note, 0) + 1
    return counts


# --- what a mechanism does to its sectors -------------------------------------------------------


def _neighbors(geometry: MapGeometry, sector: int) -> list[int]:
    """Sectors sharing a two-sided line with `sector`."""
    found = set()
    for line in geometry.linedefs:
        if line.front_sector is None or line.back_sector is None:
            continue
        if line.front_sector == sector:
            found.add(line.back_sector)
        elif line.back_sector == sector:
            found.add(line.front_sector)
    found.discard(sector)
    return sorted(found)


def apply_mechanism(
    geometry: MapGeometry, states: list[SectorState], mechanism: Mechanism
) -> list[SectorState]:
    """The sector states after the mechanism has run once, to its end position."""
    after = list(states)
    if mechanism.special.effect == Effect.TELEPORT:
        return after
    for sector in mechanism.sectors:
        after[sector] = _moved(geometry, states, sector, mechanism)
    return after


def _moved(
    geometry: MapGeometry, states: list[SectorState], sector: int, mechanism: Mechanism
) -> SectorState:
    state = states[sector]
    effect = mechanism.special.effect
    if effect == Effect.OPEN_DOOR:
        return replace(state, ceiling=OPEN_DOOR_CEILING)
    around = _neighbors(geometry, sector)
    if effect == Effect.LIFT:
        low = min([state.floor_out, *(states[n].floor_out for n in around)])
        return replace(state, floor_in=low)
    return _floor_moved(geometry, states, sector, mechanism, around)


def _floor_moved(
    geometry: MapGeometry,
    states: list[SectorState],
    sector: int,
    mechanism: Mechanism,
    around: list[int],
) -> SectorState:
    state = states[sector]
    special = mechanism.special
    floors = [states[n].floor_out for n in around]
    if special.effect == Effect.LOWER_FLOOR_LOWEST:
        target = min([state.floor_out, *floors])
    elif special.effect == Effect.LOWER_FLOOR_HIGHEST:
        target = max(floors, default=state.floor_out) + special.amount
    elif special.effect == Effect.RAISE_FLOOR_NEXT:
        target = min((f for f in floors if f > state.floor_out), default=state.floor_out)
    elif special.effect == Effect.RAISE_FLOOR_CEILING:
        ceilings = [geometry.sectors[n].ceiling for n in around]
        margin = CRUSH_MARGIN if mechanism.number in CRUSHING_RAISERS else 0
        target = min(ceilings, default=state.ceiling) - margin
    else:
        target = state.floor_out + special.amount
    return replace(state, floor_in=target, floor_out=target)


def world_from_heights(
    geometry: MapGeometry,
    base: list[SectorState],
    mechanisms: tuple[Mechanism, ...],
    heights: Sequence[tuple[float, float]],
) -> list[SectorState]:
    """The sector states the engine reports now, as (floor, ceiling) per sector.

    Only sectors some mechanism acts on can have moved. A lift off its resting floor is a called
    lift (it rises again by itself); any other mover is taken at the height it is at.
    """
    if len(heights) != len(base):
        raise ValueError(f"engine reports {len(heights)} sectors, the map has {len(base)}")
    states = list(base)
    for mech in mechanisms:
        for sector in mech.sectors:
            states[sector] = _state_now(geometry, base, sector, mech, heights[sector])
    return states


def _state_now(
    geometry: MapGeometry,
    base: list[SectorState],
    sector: int,
    mech: Mechanism,
    height: tuple[float, float],
) -> SectorState:
    """One sector's state given the (floor, ceiling) the engine reports for it."""
    floor, ceiling = int(height[0]), int(height[1])
    effect = mech.special.effect
    if effect == Effect.LIFT:
        called = floor < base[sector].floor_out
        return _moved(geometry, base, sector, mech) if called else base[sector]
    if effect == Effect.OPEN_DOOR:
        opened = ceiling - floor >= PLAYER_HEIGHT
        return replace(base[sector], ceiling=OPEN_DOOR_CEILING if opened else ceiling)
    return SectorState(floor, floor, ceiling)
