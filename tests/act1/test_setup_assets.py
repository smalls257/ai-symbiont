import pytest

from symbiont.act1.setup_assets import BSD3_NOTICE, install_freedoom


def test_install_copies_wad_and_keeps_bsd3_notice(tmp_path):
    src = tmp_path / "src" / "freedoom2.wad"
    src.parent.mkdir()
    src.write_bytes(b"IWAD-bytes")
    dest = tmp_path / "data" / "freedoom"
    wad = install_freedoom(dest, source_wad=src)
    assert wad.read_bytes() == b"IWAD-bytes"
    notice = (dest / "NOTICE-BSD-3.txt").read_text()
    assert notice == BSD3_NOTICE
    assert "Freedoom" in notice and "Redistribution and use" in notice


def test_install_refuses_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        install_freedoom(tmp_path / "d", source_wad=tmp_path / "nope.wad")


def test_notice_is_freedooms_own_copying_text_not_retyped():
    from pathlib import Path

    import symbiont.act1.setup_assets as assets

    shipped = Path(assets.__file__).parent / "assets" / "FREEDOOM-COPYING.txt"
    assert shipped.read_text() == BSD3_NOTICE
    assert BSD3_NOTICE.startswith("Copyright © 2001-2024\nContributors to the Freedoom project.")
