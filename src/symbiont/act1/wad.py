"""Minimal Doom-format WAD reader: the static geometry of one map (pure, bytes in, data out).

ViZDoom's sector and line API cannot tell doors from other sectors, so doors, exits and keys are
read from the map data itself. Lump layouts are the vanilla Doom ones: THINGS 10 bytes, LINEDEFS 14,
SIDEDEFS 30, VERTEXES 4, SECTORS 26. Freedoom's maps use this format (not Hexen).
"""

import struct
from dataclasses import dataclass
from typing import Any

MAP_LUMPS = (
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
)
NO_SIDEDEF = 0xFFFF


class WadError(ValueError):
    """The bytes are not a WAD, or the map is not in it."""


@dataclass(frozen=True)
class Linedef:
    """A map line with its special and the sectors on each side."""

    v1: int
    v2: int
    special: int
    front_sector: int | None
    back_sector: int | None
    flags: int = 0  # bit 0: impassable to players, even when two-sided
    tag: int = 0  # the sectors the special acts on, or the teleport destination; 0: none


@dataclass(frozen=True)
class Sector:
    """A map sector's authored floor and ceiling heights and its tag."""

    floor: int
    ceiling: int
    tag: int = 0  # linedef specials with the same tag act on this sector; 0: untagged


@dataclass(frozen=True)
class Thing:
    """A placed map object."""

    x: int
    y: int
    type: int


@dataclass(frozen=True)
class MapGeometry:
    """The parsed lumps of one map."""

    vertices: list[tuple[int, int]]
    linedefs: list[Linedef]
    sectors: list[Sector]
    things: list[Thing]


HEADER_BYTES = 12
ENTRY_BYTES = 16
REQUIRED_LUMPS = {
    "THINGS": "<hhhhh",
    "LINEDEFS": "<HHHHHHH",
    "SIDEDEFS": "<hh8s8s8sH",
    "VERTEXES": "<hh",
    "SECTORS": "<hh8s8shhh",
}
RECORD_FORMATS = REQUIRED_LUMPS
UNSUPPORTED_MARKERS = {
    "BEHAVIOR": "Hexen-format map (BEHAVIOR lump)",
    "TEXTMAP": "UDMF map (TEXTMAP lump)",
}
_MAP_LUMP_SET = frozenset(MAP_LUMPS) | frozenset(UNSUPPORTED_MARKERS) | {"ENDMAP"}


def _directory(data: bytes, map_name: str) -> list[tuple[str, int, int]]:
    if data[:4] not in (b"IWAD", b"PWAD"):
        raise WadError(f"{map_name}: not a WAD file: bad magic {data[:4]!r}")
    if len(data) < HEADER_BYTES:
        raise WadError(
            f"{map_name}: WAD has a truncated header ({len(data)} of {HEADER_BYTES} bytes)"
        )
    count, dir_offset = struct.unpack_from("<ii", data, 4)
    if count < 0 or dir_offset < HEADER_BYTES or dir_offset + ENTRY_BYTES * count > len(data):
        raise WadError(
            f"{map_name}: WAD has a truncated directory "
            f"({count} entries at offset {dir_offset}, file is {len(data)} bytes)"
        )
    entries = []
    for n in range(count):
        offset, size, raw_name = struct.unpack_from("<ii8s", data, dir_offset + ENTRY_BYTES * n)
        entries.append((raw_name.rstrip(b"\0").decode("ascii", errors="replace"), offset, size))
    return entries


def _lump_bytes(data: bytes, map_name: str, name: str, offset: int, size: int) -> bytes:
    if size < 0 or offset < 0 or offset + size > len(data):
        raise WadError(
            f"{map_name}: lump {name} runs past end of file "
            f"(offset {offset}, size {size}, file {len(data)})"
        )
    return data[offset : offset + size]


def _check_map_lumps(map_name: str, names: list[str]) -> None:
    for marker, what in UNSUPPORTED_MARKERS.items():
        if marker in names:
            raise WadError(
                f"{map_name}: {what} - unsupported format, only vanilla Doom maps are read"
            )
    if "ENDMAP" in names:
        raise WadError(
            f"{map_name}: ENDMAP lump without a Doom map body "
            "- malformed or unsupported (UDMF) format"
        )
    indices = [MAP_LUMPS.index(n) for n in names]
    if indices != sorted(set(indices)):
        raise WadError(f"{map_name}: map lumps are duplicated or out of order: {names}")
    missing = [n for n in REQUIRED_LUMPS if n not in names]
    if missing:
        raise WadError(f"{map_name}: missing required lump(s) {', '.join(missing)}")


def _map_lumps(data: bytes, map_name: str) -> dict[str, bytes]:
    entries = _directory(data, map_name)
    positions = [at for at, (name, _, _) in enumerate(entries) if name == map_name]
    if not positions:
        raise WadError(f"map {map_name} not found in WAD")
    position = positions[0]
    following = []
    for entry in entries[position + 1 :]:
        if entry[0] not in _MAP_LUMP_SET:
            break
        following.append(entry)
    _check_map_lumps(map_name, [name for name, _, _ in following])
    lumps = {
        name: _lump_bytes(data, map_name, name, offset, size) for name, offset, size in following
    }
    for name, fmt in RECORD_FORMATS.items():
        _check_records(map_name, name, lumps[name], fmt)
    return lumps


def _check_records(map_name: str, lump: str, blob: bytes, fmt: str) -> None:
    size = struct.calcsize(fmt)
    if not blob:
        raise WadError(f"{map_name}: required lump {lump} is empty")
    if len(blob) % size:
        raise WadError(
            f"{map_name}: lump {lump} is {len(blob)} bytes, "
            f"not a multiple of its {size}-byte record"
        )


def _records(blob: bytes, fmt: str) -> list[tuple[Any, ...]]:
    size = struct.calcsize(fmt)
    return [struct.unpack_from(fmt, blob, at) for at in range(0, len(blob) - size + 1, size)]


def read_map(data: bytes, map_name: str) -> MapGeometry:
    """Parse one map from WAD bytes; raises WadError on a missing or malformed map."""
    lumps = _map_lumps(data, map_name)
    vertices = [(x, y) for x, y in _records(lumps["VERTEXES"], "<hh")]
    sidedef_sector = [rec[5] for rec in _records(lumps["SIDEDEFS"], "<hh8s8s8sH")]

    def sector_of(sidedef: int) -> int | None:
        return None if sidedef == NO_SIDEDEF else sidedef_sector[sidedef]

    linedefs = [
        Linedef(v1, v2, special, sector_of(front), sector_of(back), flags, tag)
        for v1, v2, flags, special, tag, front, back in _records(lumps["LINEDEFS"], "<HHHHHHH")
    ]
    sectors = [Sector(rec[0], rec[1], rec[6]) for rec in _records(lumps["SECTORS"], "<hh8s8shhh")]
    things = [
        Thing(x, y, type_) for x, y, _angle, type_, _flags in _records(lumps["THINGS"], "<hhhhh")
    ]
    return MapGeometry(vertices, linedefs, sectors, things)
