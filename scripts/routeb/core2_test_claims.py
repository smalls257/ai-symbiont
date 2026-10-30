"""Core D2 task claims: several runner processes share one seeded task order without overlap.

One process per server slot claims the next unclaimed task under a file lock and runs ALL of its
arms on its own server, so a task's arms are paired on one server. A claim that never finished
(a crash, a server that dropped) is released and its records are voided as a block, so a task is
never scored half on one server and half on another. Pure file logic; no network.
"""

import fcntl
import json
import time
import uuid
from collections.abc import Sequence
from pathlib import Path


def _events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _append(path: Path, event: dict) -> None:
    with path.open("a") as log:
        log.write(json.dumps(event | {"ts": round(time.time(), 1)}) + "\n")


class ClaimBook:
    """The claim log of one test run: claim, done and release events per task."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def _locked(self):
        guard = self._path.with_name(self._path.name + ".lock").open("w")
        fcntl.flock(guard, fcntl.LOCK_EX)
        return guard

    def _latest(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for event in _events(self._path):
            latest[event["task"]] = event
        return latest

    def claim_next(
        self, ordered: Sequence[str], skip: set[str], who: str
    ) -> tuple[str, str] | None:
        """(task, block id) of the first task in order nobody holds or finished; None if none."""
        guard = self._locked()
        try:
            latest = self._latest()
            for task in ordered:
                state = latest.get(task, {}).get("event")
                if task in skip or state in ("claim", "done"):
                    continue
                block = uuid.uuid4().hex[:12]
                _append(self._path, {"task": task, "event": "claim", "who": who, "block": block})
                return task, block
            return None
        finally:
            guard.close()

    def finish(self, task: str, block: str, who: str) -> None:
        _append(self._path, {"task": task, "event": "done", "who": who, "block": block})

    def release(self, task: str, block: str, who: str) -> None:
        """Give the task back so another server runs it whole; the caller voids the block."""
        _append(self._path, {"task": task, "event": "release", "who": who, "block": block})

    def stale_blocks(self, who: str) -> list[tuple[str, str]]:
        """(task, block) this worker claimed and never finished: a previous run of it died."""
        latest = self._latest()
        return [
            (t, e["block"]) for t, e in latest.items() if e["event"] == "claim" and e["who"] == who
        ]
