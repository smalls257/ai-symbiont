"""The event log: one JSON line per hook call, so every note has a visible cause."""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.core.house_rules import Supersession
from symbiont.core.repeat import RepeatNote
from symbiont.core.slot import Decision, event_fields
from symbiont.miner.painpoint import Signature


@dataclass(frozen=True)
class Call:
    """Which route was called and, for /observe, which harness hook fired it."""

    route: str
    hook: str
    # Whose history the call is about; lets `symbiont why` find the last note of one repository.
    project: str = ""


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

    def append_repeat(self, call: Call, found: RepeatNote) -> None:
        """Record a note a stored lesson or rule caused, with the match that fired it."""
        pain = found.lesson.pain_point if found.lesson is not None else None
        trouble = None if pain is None else [pain.signature.signal.value, *pain.signature.key]
        refs = [] if pain is None else list(pain.record_refs)
        event = {"trouble": trouble, "records": refs, "notes": [found.sentence]}
        self._write(call, {**event, "fired_by": found.why})

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

    def append_note_shown(self, call: Call, note_id: str, rule: str) -> None:
        """Record a Plug note that was shown: which lesson and which rule let it through."""
        self._write(call, {"note_shown": {"note_id": note_id, "rule": rule}})

    def append_note_outcome(self, call: Call, note_id: str, rule: str, actions: list[str]) -> None:
        """Record what the agent's next actions were after the note (followed/ignored/burned)."""
        self._write(call, {"note_outcome": {"note_id": note_id, "rule": rule, "actions": actions}})

    def append_note_held(self, call: Call, why: str, numbers: dict[str, float | None]) -> None:
        """Record why Plug stayed silent (which bar blocked it, with the scores), never the text."""
        self._write(call, {"note_held": {"why": why, **numbers}})

    def append_reflection(self, call: Call, stage: str, fields: dict[str, object]) -> None:
        """Record a reflection `decision` (asked or why not) or `outcome` (lessons saved)."""
        self._write(call, {"reflection": {"stage": stage, **fields}})

    def append_superseded(self, call: Call, retired: Sequence[Supersession]) -> None:
        """Record rules that matched this work but were put aside for a later correction."""
        if not retired:
            return
        entries = [
            {
                "lesson": one.older,
                "by": one.newer,
                "lesson_excerpt": one.older_excerpt,
                "by_excerpt": one.newer_excerpt,
            }
            for one in retired
        ]
        self._write(call, {"superseded": entries, "notes": []})

    def append_failure(self, call: Call, status: int, reason: str) -> None:
        """Record a call that was refused, so a failure is never silent."""
        self._write(call, {"status": status, "reason": reason})

    def _write(self, call: Call, event: dict[str, object]) -> None:
        """Append one timestamped event line."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamped = {"ts": time.time(), "route": call.route, "hook": call.hook, **event}
        if call.project:
            stamped["project"] = call.project
        line = json.dumps({**stamped, "filler": self.filler})
        with self.path.open("a", encoding="utf-8") as log:
            log.write(line + "\n")


def last_note_event(runs_dir: Path, project: str) -> dict[str, Any] | None:
    """The newest logged event of `project` that carried a note, searching the newest run first.

    Returns None when there is none. A line that is not JSON raises ValueError naming the file.
    """
    for events in sorted(runs_dir.glob("*/events.jsonl"), reverse=True):
        for line in reversed(events.read_text(encoding="utf-8").splitlines()):
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{events} holds a line that is not JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"{events} holds a line that is not a JSON object")
            if event.get("project") == project and event.get("notes"):
                return event
    return None
