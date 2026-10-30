"""Airplane test and import rules for the pure core.

The core (records, miner, core) must reason with no network, no clock and no
harness, so it can be unit-tested on a plane and swapped without dragging its
environment along.
"""

import socket
from pathlib import Path

import pytest

from airplane import AirplaneViolationError
from import_rules import impure_imports, private_cross_imports


def test_core_has_no_network():
    with pytest.raises(AirplaneViolationError):
        socket.socket()
    with pytest.raises(AirplaneViolationError):
        socket.create_connection(("127.0.0.1", 9))


@pytest.mark.periphery
def test_periphery_marker_allows_sockets():
    sock = socket.socket()
    sock.close()


SRC = Path(__file__).resolve().parents[1] / "src" / "symbiont"
PURE_PACKAGES = ("core", "miner", "records", "routeb")


def _python_files(*packages: str) -> list[Path]:
    return [p for pkg in packages for p in sorted((SRC / pkg).rglob("*.py"))]


def test_scanner_catches_network_clock_and_periphery_imports():
    source = (
        "import socket\n"
        "from urllib.request import urlopen\n"
        "import time\n"
        "from datetime import datetime\n"
        "stamp = datetime.now()\n"
        "from symbiont.store.local import Store\n"
        "import json\n"
    )
    found = impure_imports(source)
    assert found == [
        "socket",
        "urllib.request",
        "time",
        "datetime.now",
        "symbiont.store.local",
    ]


def test_core_imports_are_pure():
    offenders = {
        str(path.relative_to(SRC)): found
        for path in _python_files(*PURE_PACKAGES)
        if (found := impure_imports(path.read_text()))
    }
    assert offenders == {}


def test_scanner_catches_private_names_from_other_packages():
    source = (
        "from symbiont.miner.signals import _helper\n"
        "from symbiont.records._codec import load\n"
        "from symbiont.readers.errors import ReadError\n"
        "from symbiont.readers import _own_helper\n"
        "import symbiont.miner._internal\n"
    )
    found = private_cross_imports(source, own_package="readers")
    assert found == [
        "symbiont.miner.signals._helper",
        "symbiont.records._codec.load",
        "symbiont.miner._internal",
    ]


def test_no_cross_internals():
    offenders = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        own = rel.parts[0] if len(rel.parts) > 1 else ""
        if found := private_cross_imports(path.read_text(), own_package=own):
            offenders[str(rel)] = found
    assert offenders == {}
