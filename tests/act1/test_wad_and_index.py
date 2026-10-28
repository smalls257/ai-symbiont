import struct

import pytest

from symbiont.act1.map_index import build_index, closed_sector_ids
from symbiont.act1.wad import WadError, read_map
from wad_builder import build_wad, linedefs, sample_wad, sectors, sidedefs, vertexes


def test_read_map_resolves_lines_to_vertices_and_sidedef_sectors():
    geometry = read_map(sample_wad(), "MAP01")
    assert len(geometry.linedefs) == 5 and len(geometry.sectors) == 3
    blue = geometry.linedefs[0]
    assert blue.special == 26
    assert (blue.front_sector, blue.back_sector) == (0, 1)
    assert geometry.vertices[blue.v1] == (100, 0) and geometry.vertices[blue.v2] == (100, 64)
    assert geometry.linedefs[2].back_sector is None
    assert geometry.sectors[1].floor == 0 and geometry.sectors[1].ceiling == 0
    assert [t.type for t in geometry.things] == [1, 5, 38, 3004]


def test_read_map_raises_on_missing_map_and_bad_header():
    with pytest.raises(WadError, match="MAP02"):
        read_map(sample_wad(), "MAP02")
    with pytest.raises(WadError, match="not a WAD"):
        read_map(b"nonsense-bytes-here", "MAP01")


def _lumps(**overrides):
    base = {
        "THINGS": b"\0" * 10,
        "LINEDEFS": b"\0" * 14,
        "SIDEDEFS": b"\0" * 30,
        "VERTEXES": b"\0" * 4,
        "SECTORS": b"\0" * 26,
    }
    base.update(overrides)
    return base


def _raw_wad(entries, magic=b"PWAD"):
    """entries: (name, data) in directory order, with no map-order assumptions (malformed WADs)."""
    body, directory, offset = b"", b"", 12
    for name, data in entries:
        directory += struct.pack("<ii8s", offset, len(data), name.encode().ljust(8, b"\0"))
        body += data
        offset += len(data)
    return magic + struct.pack("<ii", len(entries), 12 + len(body)) + body + directory


def _map_entries(lumps, extra=()):
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
    return [("MAP01", b"")] + [(n, lumps[n]) for n in order if n in lumps] + list(extra)


def test_a_well_formed_hand_built_map_reads():
    geometry = read_map(_raw_wad(_map_entries(_lumps())), "MAP01")
    assert len(geometry.linedefs) == 1 and len(geometry.sectors) == 1


def test_bad_magic_names_the_problem():
    with pytest.raises(WadError, match=r"MAP01.*bad magic"):
        read_map(b"JUNK" + _raw_wad(_map_entries(_lumps()))[4:], "MAP01")


def test_truncated_header_raises_wad_error():
    with pytest.raises(WadError, match=r"MAP01.*truncated header"):
        read_map(b"PWAD\x01\0", "MAP01")


def test_truncated_directory_raises_wad_error_not_struct_error():
    wad = _raw_wad(_map_entries(_lumps()))
    with pytest.raises(WadError, match=r"MAP01.*truncated directory"):
        read_map(wad[:-10], "MAP01")


def test_lump_past_end_of_file_raises_naming_map_and_lump():
    entries = _map_entries(_lumps())
    wad = bytearray(_raw_wad(entries))
    dir_offset = struct.unpack_from("<i", wad, 8)[0]
    size_at = dir_offset + 16 * 2 + 4  # LINEDEFS entry size field
    struct.pack_into("<i", wad, size_at, 100000)
    with pytest.raises(WadError, match=r"MAP01.*LINEDEFS.*past end of file"):
        read_map(bytes(wad), "MAP01")


@pytest.mark.parametrize(
    "lump, size",
    [("THINGS", 11), ("LINEDEFS", 15), ("SIDEDEFS", 31), ("VERTEXES", 5), ("SECTORS", 27)],
)
def test_lump_size_not_a_multiple_of_the_record_size_raises(lump, size):
    wad = _raw_wad(_map_entries(_lumps(**{lump: b"\0" * size})))
    with pytest.raises(WadError, match=rf"MAP01.*{lump}.*multiple"):
        read_map(wad, "MAP01")


@pytest.mark.parametrize("lump", ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS"])
def test_missing_required_lump_raises_naming_it(lump):
    lumps = _lumps()
    del lumps[lump]
    with pytest.raises(WadError, match=rf"MAP01.*missing.*{lump}"):
        read_map(_raw_wad(_map_entries(lumps)), "MAP01")


def test_empty_required_lump_raises_instead_of_yielding_an_empty_map():
    with pytest.raises(WadError, match=r"MAP01.*LINEDEFS.*empty"):
        read_map(_raw_wad(_map_entries(_lumps(LINEDEFS=b""))), "MAP01")


def test_lumps_out_of_order_raise():
    lumps = _lumps()
    entries = _map_entries(lumps)
    entries[1], entries[2] = entries[2], entries[1]
    with pytest.raises(WadError, match=r"MAP01.*out of order"):
        read_map(_raw_wad(entries), "MAP01")


def test_bare_endmap_without_textmap_is_a_malformed_map_not_a_value_error():
    wad = _raw_wad([("MAP01", b""), ("ENDMAP", b"")])
    with pytest.raises(WadError, match=r"MAP01.*ENDMAP.*unsupported"):
        read_map(wad, "MAP01")


def test_hexen_behavior_lump_is_an_unsupported_format():
    wad = _raw_wad(_map_entries(_lumps(), extra=[("BEHAVIOR", b"ACS\0")]))
    with pytest.raises(WadError, match=r"MAP01.*Hexen.*unsupported"):
        read_map(wad, "MAP01")


def test_udmf_textmap_is_an_unsupported_format():
    wad = _raw_wad([("MAP01", b""), ("TEXTMAP", b'namespace="zdoom";'), ("ENDMAP", b"")])
    with pytest.raises(WadError, match=r"MAP01.*UDMF.*unsupported"):
        read_map(wad, "MAP01")


def test_index_lists_doors_with_static_key_colour_and_door_sector():
    index = build_index(read_map(sample_wad(), "MAP01"))
    by_line = {d.line: d for d in index.doors}
    assert set(by_line) == {0, 1}
    assert by_line[0].key_colour == "blue" and by_line[0].mid == (100.0, 32.0)
    assert by_line[1].key_colour is None and by_line[1].mid == (32.0, 200.0)
    assert by_line[0].sector == 1 and by_line[1].sector == 1  # the sector with floor == ceiling


def test_index_lists_exits_and_secret_exits():
    index = build_index(read_map(sample_wad(), "MAP01"))
    assert [(e.line, e.secret) for e in index.exits] == [(2, False), (3, True)]


def test_index_lists_keys_by_thing_type_with_colour_and_kind():
    index = build_index(read_map(sample_wad(), "MAP01"))
    assert [(k.color, k.kind, k.x, k.y) for k in index.keys] == [
        ("blue", "card", 10, 10),
        ("red", "skull", 50, 50),
    ]


def test_every_documented_door_special_maps_to_the_right_colour():
    from symbiont.act1.map_index import DOOR_SPECIALS

    # Vanilla Doom manual doors, Chocolate Doom p_switch.c P_UseSpecialLine.
    assert {s for s, c in DOOR_SPECIALS.items() if c is None} == {1, 31, 117, 118}
    assert {s: c for s, c in DOOR_SPECIALS.items() if c} == {
        26: "blue",
        27: "yellow",
        28: "red",
        32: "blue",
        33: "red",
        34: "yellow",
    }


def test_closed_sector_ids_uses_runtime_floor_and_ceiling():
    assert closed_sector_ids([(0, 128), (0, 0), (0, 40)]) == frozenset({1})


def test_read_map_keeps_the_linedef_flags_so_impassable_lines_are_known():
    wad = build_wad(
        "MAP01",
        {
            "THINGS": b"\0" * 10,
            "VERTEXES": vertexes([(0, 0), (64, 0)]),
            "SIDEDEFS": sidedefs([0, 0]),
            "SECTORS": sectors([(0, 128)]),
            "LINEDEFS": linedefs([(0, 1, 0, 0, 1, 1)]),
        },
    )
    assert read_map(wad, "MAP01").linedefs[0].flags == 1
