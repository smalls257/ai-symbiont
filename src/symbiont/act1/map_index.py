"""Static index of a map's doors, exits and keys, built from its WAD geometry (pure).

Specials come from vanilla Doom's use/cross handlers, as in Chocolate Doom's src/doom/p_switch.c
(P_UseSpecialLine: manual doors 1, 26-28, 31-34, 117, 118; exit switches 11, 51) and
src/doom/p_spec.c (P_CrossSpecialLine: exit walkovers 52, 124). Keyed manual doors give their key
colour statically, so "needs a blue key" never depends on an engine message. Remote switch and
walkover doors act on a tagged sector and are not listed: open_door presses USE on the door itself.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from symbiont.act1.wad import Linedef, MapGeometry, Sector

# special -> key colour (None: no key needed)
DOOR_SPECIALS: dict[int, str | None] = {
    1: None,
    26: "blue",
    27: "yellow",
    28: "red",
    31: None,
    32: "blue",
    33: "red",
    34: "yellow",
    117: None,
    118: None,
}
EXIT_SPECIALS = {11: False, 52: False, 51: True, 124: True}  # special -> leads to the secret level
KEY_THINGS = {  # THINGS type -> (colour, kind)
    5: ("blue", "card"),
    6: ("yellow", "card"),
    13: ("red", "card"),
    40: ("blue", "skull"),
    39: ("yellow", "skull"),
    38: ("red", "skull"),
}
CLOSED_GAP = 1  # a door sector is shut when its ceiling is within this of its floor


@dataclass(frozen=True)
class StaticDoor:
    """A door line as authored in the map."""

    line: int
    mid: tuple[float, float]
    sector: int | None  # the sector that rises when the door opens
    key_colour: str | None


@dataclass(frozen=True)
class StaticExit:
    """An exit line as authored in the map."""

    line: int
    mid: tuple[float, float]
    secret: bool


@dataclass(frozen=True)
class StaticKey:
    """A key pickup as authored in the map."""

    colour: str
    kind: str
    x: int
    y: int


@dataclass(frozen=True)
class MapIndex:
    """Doors, exits and keys of one map, read from its WAD rather than the engine."""

    doors: tuple[StaticDoor, ...]
    exits: tuple[StaticExit, ...]
    keys: tuple[StaticKey, ...]
    sectors: tuple[Sector, ...] = ()  # as authored; the reference for checking the engine's heights


def _midpoint(geometry: MapGeometry, line: Linedef) -> tuple[float, float]:
    (x1, y1), (x2, y2) = geometry.vertices[line.v1], geometry.vertices[line.v2]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _door_sector(geometry: MapGeometry, line: Linedef) -> int | None:
    """Of the two sectors on a door line, the one built shut (smallest floor-to-ceiling gap)."""
    sides = [sector for sector in (line.front_sector, line.back_sector) if sector is not None]
    return min(
        sides,
        key=lambda sector: geometry.sectors[sector].ceiling - geometry.sectors[sector].floor,
        default=None,
    )


def build_index(geometry: MapGeometry) -> MapIndex:
    """List the map's doors, exits and keys from its linedefs and things."""
    doors, exits = [], []
    for number, line in enumerate(geometry.linedefs):
        if line.special in DOOR_SPECIALS:
            doors.append(
                StaticDoor(
                    number,
                    _midpoint(geometry, line),
                    _door_sector(geometry, line),
                    DOOR_SPECIALS[line.special],
                )
            )
        elif line.special in EXIT_SPECIALS:
            exits.append(StaticExit(number, _midpoint(geometry, line), EXIT_SPECIALS[line.special]))
    keys = [
        StaticKey(*KEY_THINGS[t.type], t.x, t.y) for t in geometry.things if t.type in KEY_THINGS
    ]
    return MapIndex(tuple(doors), tuple(exits), tuple(keys), tuple(geometry.sectors))


def closed_sector_ids(heights: Iterable[tuple[float, float]]) -> frozenset[int]:
    """Indexes of sectors whose ceiling has dropped to the floor, from (floor, ceiling) pairs."""
    return frozenset(
        n for n, (floor, ceiling) in enumerate(heights) if abs(ceiling - floor) <= CLOSED_GAP
    )
