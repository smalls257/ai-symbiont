"""Freedoom asset setup (periphery: touches the filesystem and the installed vizdoom package).

Freedoom only, no id Software assets. The ViZDoom pip package bundles
freedoom2.wad (BSD-3), so we copy that into data/freedoom/ instead of
downloading, and keep the BSD-3 notice beside it. data/ is gitignored: the
WAD is never committed.
"""

import logging
import shutil
from pathlib import Path

progress = logging.getLogger(__name__)

# Freedoom's COPYING text (BSD-3-Clause), fetched once from
# https://raw.githubusercontent.com/freedoom/freedoom/master/COPYING.adoc (the vizdoom wheel ships
# freedoom2.wad without it) and stored verbatim as a package asset.
BSD3_NOTICE = (Path(__file__).parent / "assets" / "FREEDOOM-COPYING.txt").read_text()

WAD_NAME = "freedoom2.wad"
NOTICE_NAME = "NOTICE-BSD-3.txt"


def bundled_wad_path() -> Path:
    """The freedoom2.wad shipped inside the vizdoom package."""
    import vizdoom

    return Path(vizdoom.__file__).parent / WAD_NAME


def install_freedoom(dest: Path, source_wad: Path | None = None) -> Path:
    """Copy the WAD into `dest` with the BSD-3 notice; returns the installed WAD path."""
    source = source_wad if source_wad is not None else bundled_wad_path()
    if not source.is_file():
        raise FileNotFoundError(f"Freedoom WAD not found at {source}")
    dest.mkdir(parents=True, exist_ok=True)
    wad = dest / WAD_NAME
    shutil.copyfile(source, wad)
    (dest / NOTICE_NAME).write_text(BSD3_NOTICE)
    return wad


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    progress.info("%s", install_freedoom(Path("data") / "freedoom"))
