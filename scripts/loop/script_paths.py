"""Put the sibling script directories the real domain plugins import on `sys.path`.

The plugins reuse scripts, not packages: `scripts/routeb/general_*` (coding) and
`scripts/act1/build_lesson_set.py` (Freedoom). Entry points call `add_script_dirs()` before they
import a plugin, the same way each script directory already finds its own siblings.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SIBLINGS = ("routeb", "act1", "calibration")


def add_script_dirs() -> None:
    """Prepend scripts/routeb, scripts/act1 and scripts/calibration once each."""
    for name in SIBLINGS:
        where = str(SCRIPTS / name)
        if where not in sys.path:
            sys.path.insert(0, where)
