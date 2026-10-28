"""The event log: one JSON line per hook call, so every note has a visible cause."""

import json
import time
from pathlib import Path

from symbiont.core.slot import Decision, event_fields
from symbiont.miner.painpoint import Signature


class EventLog:
    """Appends events to `<run_dir>/events.jsonl`; the file is created on first write."""

    def __init__(self, run_dir: Path, filler: str) -> None:
        self.path = run_dir / "events.jsonl"
        self.filler = filler

    def append(
        self,
        hook: str,
        signature: Signature | None,
        records: list[tuple[str, int]],
        notes: list[str],
    ) -> None:
        """Record which hook fired, the trouble named, the records behind it and the notes sent."""
        trouble = None if signature is None else [signature.signal.value, *signature.key]
        self._write(
            {
                "hook": hook,
                "signature": trouble,
                "records": records,
                "notes": notes,
                "filler": self.filler,
            }
        )

    def append_decision(self, hook: str, decision: Decision, notes: list[str]) -> None:
        """Record a decision through `event_fields`, which never carries its risk."""
        refs = [ref for pain in decision.why for ref in pain.record_refs]
        self._write(
            {
                "hook": hook,
                **event_fields(decision),
                "records": refs,
                "notes": notes,
                "filler": self.filler,
            }
        )

    def append_failure(self, hook: str, status: int, reason: str) -> None:
        """Record a call that was refused, so a failure is never silent."""
        self._write({"hook": hook, "status": status, "reason": reason, "filler": self.filler})

    def _write(self, event: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), **event})
        with self.path.open("a", encoding="utf-8") as log:
            log.write(line + "\n")
