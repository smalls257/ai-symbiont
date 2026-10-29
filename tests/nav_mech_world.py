"""Hand-built synthetic maps whose way to the exit needs a switch, a lift or a teleport.

Room A (sector 0) is x 0..256, y 0..256 and holds the start. The exit switch (special 11) is on
the east wall of the far room, so the way to the exit passes the mechanism under test.
"""

from nav_world import _Vertices
from symbiont.act1.wad import Linedef, MapGeometry, Sector, Thing

START = (64.0, 32.0)
TAG = 7


def line(verts, start, end, front, back=None, special=0, tag=0) -> Linedef:
    return Linedef(verts.index(start), verts.index(end), special, front, back, 0, tag)


def _walls_of_room_a(verts, switch: int, east_gap: tuple[int, int]) -> list[Linedef]:
    """Room A's walls: a switch on the north wall, a gap in the east wall for the next sector."""
    low, high = east_gap
    return [
        line(verts, (0, 0), (0, 256), 0),
        line(verts, (0, 256), (100, 256), 0),
        line(verts, (100, 256), (140, 256), 0, special=switch, tag=TAG),
        line(verts, (140, 256), (256, 256), 0),
        line(verts, (256, 256), (256, high), 0),
        line(verts, (256, low), (256, 0), 0),
        line(verts, (256, 0), (0, 0), 0),
    ]


def _far_room(verts, sector: int, left: int, exit_special: int = 11) -> list[Linedef]:
    """A room 256 wide starting at x=left, closed on all sides but the west gap y 96..160."""
    right = left + 256
    return [
        line(verts, (left, 160), (left, 256), sector),
        line(verts, (left, 256), (right, 256), sector),
        line(verts, (right, 256), (right, 0), sector, special=exit_special),
        line(verts, (right, 0), (left, 0), sector),
        line(verts, (left, 0), (left, 96), sector),
    ]


def switch_door(switch: int = 103, exit_special: int = 11) -> MapGeometry:
    """A closed door sector 1 (tag 7) joins room A to room B (sector 2); `switch` opens it."""
    verts = _Vertices()
    lines = _walls_of_room_a(verts, switch, (96, 160)) + _far_room(verts, 2, 272, exit_special)
    lines += [
        line(verts, (256, 160), (256, 96), 0, 1),
        line(verts, (256, 160), (272, 160), 1),
        line(verts, (272, 96), (256, 96), 1),
        line(verts, (272, 96), (272, 160), 2, 1),
    ]
    sectors = [Sector(0, 128), Sector(0, 0, TAG), Sector(0, 128)]
    return MapGeometry(verts.points, lines, sectors, [Thing(1, 1, 1)])


def lift(switch: int = 62) -> MapGeometry:
    """Room B (sector 2) is 64 up. Lift sector 1 (tag 7) rests up at 64; the switch lowers it."""
    verts = _Vertices()
    lines = _walls_of_room_a(verts, switch, (96, 160)) + _far_room(verts, 2, 320)
    lines += [
        line(verts, (256, 160), (256, 96), 0, 1),
        line(verts, (256, 160), (320, 160), 1),
        line(verts, (320, 96), (256, 96), 1),
        line(verts, (320, 96), (320, 160), 2, 1),
    ]
    sectors = [Sector(0, 192), Sector(64, 192, TAG), Sector(64, 192)]
    return MapGeometry(verts.points, lines, sectors, [Thing(1, 1, 1)])


def teleport(special: int = 97) -> MapGeometry:
    """Walls part room A from room C (sector 3, x 400..656). A pad (sector 1) in room A has a
    teleport line (tag 7) on its west edge, front side toward A; room C holds the landing (tag 7).
    """
    verts = _Vertices()
    lines = _walls_of_room_a(verts, 0, (96, 160))
    lines[4:6] = [line(verts, (256, 256), (256, 0), 0)]
    lines += _far_room(verts, 3, 400)
    lines += [line(verts, (400, 96), (400, 160), 3)]
    pad = [
        line(verts, (192, 128), (192, 96), 0, 1, special=special, tag=TAG),
        line(verts, (192, 96), (224, 96), 0, 1),
        line(verts, (224, 96), (224, 128), 0, 1),
        line(verts, (224, 128), (192, 128), 0, 1),
    ]
    sectors = [Sector(0, 128), Sector(0, 128), Sector(0, 128), Sector(0, 128, TAG)]
    things = [Thing(1, 1, 1), Thing(500, 128, 14)]
    return MapGeometry(verts.points, lines + pad, sectors, things)


def pedestal_key(switch: int = 23) -> MapGeometry:
    """A blue card on a 96-high pedestal (sector 1, tag 7) in room A; `switch` can lower it."""
    verts = _Vertices()
    lines = _walls_of_room_a(verts, switch, (96, 160))
    lines[4:6] = [line(verts, (256, 256), (256, 0), 0)]
    pedestal = [
        line(verts, (192, 128), (192, 96), 0, 1),
        line(verts, (192, 96), (224, 96), 0, 1),
        line(verts, (224, 96), (224, 128), 0, 1),
        line(verts, (224, 128), (192, 128), 0, 1),
    ]
    sectors = [Sector(0, 192), Sector(96, 192, TAG)]
    things = [Thing(1, 1, 1), Thing(208, 112, 5)]
    return MapGeometry(verts.points, lines + pedestal, sectors, things)


def closing_door(closer: int = 3, opener: int = 103) -> MapGeometry:
    """Switch door as in switch_door, but a walkover line (`closer`, tag 7) across room A lies on
    the way to the door: crossing it shuts the door again.
    """
    verts = _Vertices()
    lines = [
        line(verts, (0, 0), (0, 256), 0),
        line(verts, (0, 256), (100, 256), 0),
        line(verts, (100, 256), (140, 256), 0, special=opener, tag=TAG),
        line(verts, (140, 256), (200, 256), 0),
        line(verts, (200, 256), (256, 256), 3),
        line(verts, (256, 256), (256, 160), 3),
        line(verts, (256, 96), (256, 0), 3),
        line(verts, (256, 0), (200, 0), 3),
        line(verts, (200, 0), (0, 0), 0),
        line(verts, (200, 256), (200, 0), 0, 3, special=closer, tag=TAG),
    ]
    lines += _far_room(verts, 2, 272)
    lines += [
        line(verts, (256, 160), (256, 96), 3, 1),
        line(verts, (256, 160), (272, 160), 1),
        line(verts, (272, 96), (256, 96), 1),
        line(verts, (272, 96), (272, 160), 2, 1),
    ]
    sectors = [Sector(0, 128), Sector(0, 0, TAG), Sector(0, 128), Sector(0, 128)]
    return MapGeometry(verts.points, lines, sectors, [Thing(1, 1, 1)])


def door_chain(first: int = 29, second_switch_in_a: bool = True) -> MapGeometry:
    """A | D1 | B | D2 | C, the exit in C. A holds the switch `first` for D1 (tag 7) and, with
    `second_switch_in_a`, the switch for D2 (tag 8): after D1 is crossed the walker must come back.
    """
    verts = _Vertices()
    lines = [
        line(verts, (0, 0), (0, 256), 0),
        line(verts, (0, 256), (100, 256), 0),
        line(verts, (100, 256), (140, 256), 0, special=first, tag=TAG),
        line(verts, (140, 256), (150, 256), 0),
        line(verts, (150, 256), (190, 256), 0, special=103 if second_switch_in_a else 0, tag=8),
        line(verts, (190, 256), (256, 256), 0),
        line(verts, (256, 256), (256, 160), 0),
        line(verts, (256, 96), (256, 0), 0),
        line(verts, (256, 0), (0, 0), 0),
    ]
    lines += [
        line(verts, (272, 160), (272, 256), 2),
        line(verts, (272, 256), (528, 256), 2),
        line(verts, (528, 256), (528, 160), 2),
        line(verts, (528, 96), (528, 0), 2),
        line(verts, (528, 0), (272, 0), 2),
        line(verts, (272, 0), (272, 96), 2),
    ]
    lines += _far_room(verts, 4, 560)
    lines += [  # D1 between A and B, D2 between B and C
        line(verts, (256, 160), (256, 96), 0, 1),
        line(verts, (256, 160), (272, 160), 1),
        line(verts, (272, 96), (256, 96), 1),
        line(verts, (272, 96), (272, 160), 2, 1),
        line(verts, (528, 160), (528, 96), 2, 3),
        line(verts, (528, 160), (544, 160), 3),
        line(verts, (544, 96), (528, 96), 3),
        line(verts, (544, 96), (544, 160), 4, 3),
    ]
    sectors = [
        Sector(0, 128),
        Sector(0, 0, TAG),
        Sector(0, 128),
        Sector(0, 0, 8),
        Sector(0, 128),
    ]
    return MapGeometry(verts.points, lines, sectors, [Thing(1, 1, 1)])
