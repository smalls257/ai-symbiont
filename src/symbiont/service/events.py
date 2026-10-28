"""The event log: one JSON line per hook call, so every note has a visible cause."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from symbiont.core.slot import Decision, event_fields
from symbiont.miner.painpoint import Signature


@dataclass(frozen=True)
class Call:
    """Which route was called and, for /observe, which harness hook fired it."""

    route: str
    hook: str


@dataclass(frozen=True)
class MemoryCost:
    """What one memory-model call cost: the prompt's size and the wall-clock milliseconds."""

    prompt_chars: int
    ms: float


class EventLog:
    """Appends events to `<run_dir>/events.jsonl`; the file is created on first write."""

    def __init__(self, run_dir: Path, filler: str) -> None:
        """Log to `events.jsonl` under `run_dir`, tagging each line with `filler`."""
        self.path = run_dir / "events.jsonl"
        self.filler = filler

    def append(
        self,
        call: Call,
        signature: Signature | None,
        records: list[tuple[str, int]],
        notes: list[str],
    ) -> None:
        """Record the call, the trouble named, the records behind it and the notes sent."""
        trouble = None if signature is None else [signature.signal.value, *signature.key]
        self._write(call, {"trouble": trouble, "records": records, "notes": notes})

    def append_decision(self, call: Call, decision: Decision, notes: list[str]) -> None:
        """Record a decision through `event_fields`, which never carries its risk."""
        refs = [ref for pain in decision.why for ref in pain.record_refs]
        refs += [(r.session_id, r.step) for r in decision.recall]
        self._write(call, {**event_fields(decision), "records": refs, "notes": notes})

    def append_memory_note(
        self, call: Call, decision: Decision | None, note: str, cost: MemoryCost
    ) -> None:
        """Record a note the memory model wrote: sizes and milliseconds, never the prompt."""
        decided = event_fields(decision) if decision is not None else {"trouble": None}
        timing = {"prompt_chars": cost.prompt_chars, "note_chars": len(note), "ms": cost.ms}
        self._write(call, {**decided, "records": [], "notes": [note], "memory_model": timing})

    def append_quiet(self, call: Call, decision: Decision, why: str) -> None:
        """Record a decision to speak that the delivery rule held back, and why."""
        self._write(call, {**event_fields(decision), "records": [], "notes": [], "held": why})

    def append_failure(self, call: Call, status: int, reason: str) -> None:
        """Record a call that was refused, so a failure is never silent."""
        self._write(call, {"status": status, "reason": reason})

    def _write(self, call: Call, event: dict[str, object]) -> None:
        """Append one timestamped event line."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamped = {"ts": time.time(), "route": call.route, "hook": call.hook, **event}
        line = json.dumps({**stamped, "filler": self.filler})
        with self.path.open("a", encoding="utf-8") as log:
            log.write(line + "\n")
