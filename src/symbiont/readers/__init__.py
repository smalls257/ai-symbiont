"""History readers: one module per coding harness.

Each exposes `read(path, project) -> Iterator[Record]`.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

from symbiont.readers import mini_swe_agent, openhands
from symbiont.records.schema import Record

Reader = Callable[[Path, str], Iterator[Record]]

READERS: dict[str, Reader] = {
    "mini-swe-agent": mini_swe_agent.read,
    "openhands": openhands.read,
}
