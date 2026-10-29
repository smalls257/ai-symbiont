"""Put the sibling script directories on sys.path so scripts import each other by module name."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def add_script_dirs() -> None:
    """Add scripts/evolve and scripts/act1 once."""
    for name in ("evolve", "act1"):
        path = str(SCRIPTS / name)
        if path not in sys.path:
            sys.path.insert(0, path)
