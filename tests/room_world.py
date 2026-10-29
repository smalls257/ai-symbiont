"""Shared synthetic map for room-lookup tests (hand-written, no game data)."""

from symbiont.act1.wad import Linedef, MapGeometry, Sector


def two_rooms_with_a_pillar() -> MapGeometry:
    """Room 0 is x 0..100, room 1 is x 100..200 (both y 0..100); sector 2 is a pillar in room 0."""
    vertices = [
        (0, 0), (100, 0), (200, 0), (200, 100), (100, 100), (0, 100),
        (40, 40), (60, 40), (60, 60), (40, 60),
    ]  # fmt: skip
    one_sided = [(0, 1, 0), (1, 2, 1), (2, 3, 1), (3, 4, 1), (4, 5, 0), (5, 0, 0)]
    lines = [Linedef(a, b, 0, s, None) for a, b, s in one_sided]
    lines.append(Linedef(1, 4, 0, 1, 0))  # the opening between the rooms
    pillar = [(6, 7), (7, 8), (8, 9), (9, 6)]
    lines += [Linedef(a, b, 0, 2, 0) for a, b in pillar]
    return MapGeometry(vertices, lines, [Sector(0, 128)] * 3, [])
