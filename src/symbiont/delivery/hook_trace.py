"""Opt-in hook trace: a line on receipt (before parsing) and a line with the outcome, per hook.

Off by default. On with `SYMBIONT_HOOK_TRACE=<file>`, or a `hook-trace.on` file in the data
directory (Muse Code starts hooks without the user's environment variables, so only a file works).
"""

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

TRACE_VARIABLE = "SYMBIONT_HOOK_TRACE"
TRACE_MARKER = "hook-trace.on"
TRACE_FILE = "hook-trace.jsonl"


def trace_path(environ: Mapping[str, str], data_dir: Path) -> Path | None:
    """Where to trace, or None when tracing is off."""
    named = environ.get(TRACE_VARIABLE, "")
    if named:
        return Path(named)
    return data_dir / TRACE_FILE if (data_dir / TRACE_MARKER).exists() else None


def record_received(path: Path | None, event: str, stdin_text: str) -> None:
    """Append what arrived, byte for byte, before anything reads it."""
    _append(path, {"stage": "received", "event": event, "stdin": stdin_text})


def record_outcome(path: Path | None, event: str, outcome: str, why: str = "") -> None:
    """Append what the hook did: `forwarded`, or `dropped` with the reason."""
    _append(path, {"stage": "outcome", "event": event, "outcome": outcome, "why": why})


def _append(path: Path | None, line: dict[str, object]) -> None:
    if path is None:
        return
    stamped = {"ts": time.time(), "pid": os.getpid()} | line
    with path.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(stamped) + "\n")
