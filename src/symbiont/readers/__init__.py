"""History readers: one module per coding harness.

Each exposes `read(path, project) -> Iterator[Record]`.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

from symbiont.readers import openhands
from symbiont.records.schema import Record

Reader = Callable[[Path, str], Iterator[Record]]

READERS: dict[str, Reader] = {
    "openhands": openhands.read,
}
