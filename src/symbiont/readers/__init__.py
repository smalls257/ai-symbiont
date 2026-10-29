"""History readers: one module per coding harness.

Each exposes `read(path, project) -> Iterator[Record]`.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

from symbiont.readers import claude_code, mini_swe_agent, openhands
from symbiont.records.schema import Record

Reader = Callable[[Path, str], Iterator[Record]]

READERS: dict[str, Reader] = {
    "claude-code": claude_code.read,
    "swe-chat": claude_code.read_swe_chat,
    "open-swe-traces-claudecode": claude_code.read_open_swe_traces,
    "mini-swe-agent": mini_swe_agent.read,
    "open-swe-traces-minisweagent": mini_swe_agent.read_open_swe_traces,
    "local-run": mini_swe_agent.read_local_run,
    "openhands": openhands.read,
}
