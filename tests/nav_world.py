"""Hand-built synthetic maps for navigation tests (no WAD bytes, no engine).

Two rooms side by side. Room A (sector 0) spans x 0..256, room B (sector 2) x 272..528,
both y 0..256. Between them a 16-unit-thick door sector (1), closed (floor == ceiling),
spanning y 96..160. Room B's east wall carries an exit switch (special 11);
room A holds a blue card at (64, 128).
"""

from symbiont.act1.map_index import MapIndex, build_index
from symbiont.act1.wad import Linedef, MapGeometry, Sector, Thing

ROOM_A, DOOR, ROOM_B = 0, 1, 2
START = (64.0, 32.0)
EXIT_MID = (528.0, 128.0)
CARD = (64.0, 128.0)


class _Vertices:
    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def index(self, point: tuple[int, int]) -> int:
        if point not in self.points:
            self.points.append(point)
        return self.points.index(point)


def _line(vertices: _Vertices, a, b, front, back=None, special=0, flags=0) -> Linedef:
    return Linedef(vertices.index(a), vertices.index(b), special, front, back, flags)


def two_rooms(
    door_special: int | None = 1,
    sector_heights: list[tuple[int, int]] | None = None,
    window_flags: int | None = None,
    faces: str = "both",
) -> MapGeometry:
    """door_special None: the gap between the rooms is solid wall, or, with `window_flags`
    given, one two-sided line between the rooms carrying those linedef flags (1 = impassable).
    `faces` says which door face carries the use-special: "both", "a" (room A's face only)
    or "b" (room B's only), since USE works only from the front of a special line."""
    v = _Vertices()
    lines = [
        _line(v, (0, 0), (0, 256), ROOM_A),
        _line(v, (0, 256), (256, 256), ROOM_A),
        _line(v, (256, 256), (256, 160), ROOM_A),
        _line(v, (256, 96), (256, 0), ROOM_A),
        _line(v, (256, 0), (0, 0), ROOM_A),
        _line(v, (272, 0), (272, 96), ROOM_B),
        _line(v, (272, 160), (272, 256), ROOM_B),
        _line(v, (272, 256), (528, 256), ROOM_B),
        _line(v, (528, 256), (528, 0), ROOM_B, special=11),
        _line(v, (528, 0), (272, 0), ROOM_B),
    ]
    if door_special is None and window_flags is not None:
        lines += [_line(v, (256, 160), (256, 96), ROOM_A, ROOM_B, flags=window_flags)]
    elif door_special is None:
        lines += [_line(v, (256, 160), (256, 96), ROOM_A), _line(v, (272, 96), (272, 160), ROOM_B)]
    else:
        lines += [
            _line(
                v,
                (256, 160),
                (256, 96),
                ROOM_A,
                DOOR,
                door_special if faces in ("both", "a") else 0,
            ),
            _line(v, (256, 160), (272, 160), DOOR),
            _line(v, (272, 96), (256, 96), DOOR),
            _line(
                v,
                (272, 96),
                (272, 160),
                ROOM_B,
                DOOR,
                door_special if faces in ("both", "b") else 0,
            ),
        ]
    sectors = sector_heights or [(0, 128), (0, 0), (0, 128)]
    things = [Thing(1, 1, 1), Thing(CARD[0], CARD[1], 5)]
    return MapGeometry(v.points, lines, [Sector(f, c) for f, c in sectors], things)


def two_rooms_index(geometry: MapGeometry | None = None) -> tuple[MapGeometry, MapIndex]:
    geometry = geometry or two_rooms()
    return geometry, build_index(geometry)


def trench_rooms(width: int, depth: int = 400) -> MapGeometry:
    """Room A (x 0..256) and room B (x 256+width..) on the same floor.

    A `depth`-deep trench lies between them.

    A player cannot climb out of a deep trench, but straddles a narrow one without noticing it.
    """
    v = _Vertices()
    right_of_trench = 256 + width
    lines = [
        _line(v, (0, 0), (0, 256), 0),
        _line(v, (0, 256), (256, 256), 0),
        _line(v, (256, 256), (256, 0), 0, 1),  # A | trench
        _line(v, (256, 0), (0, 0), 0),
        _line(v, (256, 256), (right_of_trench, 256), 1),
        _line(v, (right_of_trench, 0), (256, 0), 1),
        _line(v, (right_of_trench, 0), (right_of_trench, 256), 2, 1),  # trench | B
        _line(v, (right_of_trench, 256), (right_of_trench + 256, 256), 2),
        _line(v, (right_of_trench + 256, 256), (right_of_trench + 256, 0), 2, special=11),
        _line(v, (right_of_trench + 256, 0), (right_of_trench, 0), 2),
    ]
    sectors = [Sector(0, 128), Sector(-depth, 128), Sector(0, 128)]
    return MapGeometry(v.points, lines, sectors, [Thing(1, 1, 1)])


def ledge_room() -> MapGeometry:
    """One room (x 0..512, y 0..256) with a 64-high ledge block (x 200..300, y 0..200) in the way.

    Straight east along y=128 climbs the ledge; the walkable way is round the top,
    through y 200..256.
    """
    v = _Vertices()
    lines = [
        _line(v, (0, 0), (0, 256), 0),
        _line(v, (0, 256), (512, 256), 0),
        _line(v, (512, 256), (512, 0), 0),
        _line(v, (512, 0), (300, 0), 0),
        _line(v, (300, 0), (200, 0), 1),
        _line(v, (200, 0), (0, 0), 0),
        _line(v, (200, 0), (200, 200), 1, 0),
        _line(v, (200, 200), (300, 200), 1, 0),
        _line(v, (300, 200), (300, 0), 1, 0),
    ]
    return MapGeometry(v.points, lines, [Sector(0, 128), Sector(64, 128)], [Thing(1, 1, 1)])
