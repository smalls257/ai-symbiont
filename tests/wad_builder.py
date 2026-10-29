"""Hand-built Doom-format PWAD bytes for tests.

A tiny map with a keyed door, a plain door and an exit.
"""

import struct

NO_SIDE = 0xFFFF


def _lump_name(name: str) -> bytes:
    return name.encode("ascii").ljust(8, b"\0")


def things(entries):
    return b"".join(struct.pack("<hhhhh", x, y, 0, type_, 7) for x, y, type_ in entries)


def linedefs(entries):
    """entries: (v1, v2, special, front_sidedef, back_sidedef[, flags[, tag]])."""
    return b"".join(
        struct.pack(
            "<HHHHHHH",
            e[0],
            e[1],
            e[5] if len(e) > 5 else 0,
            e[2],
            e[6] if len(e) > 6 else 0,
            e[3],
            e[4],
        )
        for e in entries
    )


def sidedefs(sector_ids):
    return b"".join(
        struct.pack("<hh8s8s8sH", 0, 0, b"-", b"-", b"-", sector) for sector in sector_ids
    )


def vertexes(points):
    return b"".join(struct.pack("<hh", x, y) for x, y in points)


def sectors(heights):
    """heights: (floor, ceiling[, tag])."""
    return b"".join(
        struct.pack("<hh8s8shhh", h[0], h[1], b"FLOOR", b"CEIL", 160, 0, h[2] if len(h) > 2 else 0)
        for h in heights
    )


def build_wad(map_name: str, lumps: dict[str, bytes]) -> bytes:
    """A PWAD holding `map_name` (an empty marker lump), then the given map lumps in Doom order."""
    order = [
        "THINGS",
        "LINEDEFS",
        "SIDEDEFS",
        "VERTEXES",
        "SEGS",
        "SSECTORS",
        "NODES",
        "SECTORS",
        "REJECT",
        "BLOCKMAP",
    ]
    entries = [(map_name, b"")] + [(name, lumps.get(name, b"")) for name in order]
    body = b""
    directory = b""
    offset = 12
    for name, data in entries:
        directory += struct.pack("<ii8s", offset if data else 0, len(data), _lump_name(name))
        body += data
        offset += len(data)
    return b"PWAD" + struct.pack("<ii", len(entries), 12 + len(body)) + body + directory


def sample_wad() -> bytes:
    """Sectors: 0 room, 1 closed door (floor == ceiling), 2 room.

    Lines: 0 blue-keyed door (special 26), 1 plain door (special 1), 2 exit switch (special 11),
    3 secret exit (special 51), 4 ordinary wall.
    """
    return build_wad(
        "MAP01",
        {
            "THINGS": things([(1, 1, 1), (10, 10, 5), (50, 50, 38), (70, 70, 3004)]),
            "VERTEXES": vertexes(
                [(100, 0), (100, 64), (0, 200), (64, 200), (300, 0), (300, 64), (0, 0), (64, 0)]
            ),
            "SIDEDEFS": sidedefs([0, 1, 1, 0, 0]),
            "SECTORS": sectors([(0, 128), (0, 0), (0, 128)]),
            "LINEDEFS": linedefs(
                [
                    (0, 1, 26, 0, 1),  # blue door: front room 0, back door sector 1
                    (2, 3, 1, 2, 3),  # plain door: front door sector 1, back room 0
                    (4, 5, 11, 4, NO_SIDE),  # exit
                    (6, 7, 51, 4, NO_SIDE),  # secret exit
                    (0, 2, 0, 4, NO_SIDE),  # wall
                ]
            ),
        },
    )
