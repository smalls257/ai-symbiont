"""One session as the session page shows it: strip, your messages, failed commands, counts.

Everything text-shaped is scrubbed before it is cut, so a cut can never expose half a credential.
Pure: records in, a JSON-ready detail out. Reading the log is the service's job.
"""

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from symbiont.miner.commands import NO_PATH, program_words
from symbiont.miner.credential_patterns import scrub
from symbiont.miner.error_lines import key_error_lines
from symbiont.miner.session_digest import digest_of, typed_message
from symbiont.miner.strips import Lane, StripStep, densest_window, strip_of
from symbiont.miner.themes import Codebase
from symbiont.miner.tool_messages import raw_complaint
from symbiont.records.schema import Record

# The strip page draws as many steps as the home page's strip does (strips.MAX_STRIP_STEPS).
DEFAULT_MAX_STEPS = 600
MESSAGE_CHARS = 300
NEIGHBOR_CHARS = 80
COMMAND_CHARS = 160
ERROR_CHARS = 160
# A longer gap is the developer away or a session resumed later, not time spent on the session.
ACTIVE_GAP_MINUTES = 30
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")
_ISO_TIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$"
)


@dataclass(frozen=True)
class SessionDetail:
    """The page's data for one session; `as_json` is what the endpoint sends."""

    goal: str | None
    date: str | None
    minutes: int | None
    total: int
    steps: tuple[StripStep, ...]
    messages: tuple[dict[str, Any], ...]
    failed: tuple[dict[str, Any], ...]
    counts: dict[str, int] = field(default_factory=dict)
    shown_counts: dict[str, int] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        """The detail as plain JSON values."""
        return {
            "goal": self.goal,
            "date": self.date,
            "minutes": self.minutes,
            "total": self.total,
            "shown": len(self.steps),
            "steps": [[s.step, s.lane.value, s.label] for s in self.steps],
            "messages": list(self.messages),
            "failed": list(self.failed),
            "counts": self.counts,
            "shownCounts": self.shown_counts,
        }


def session_detail(
    records: Sequence[Record], *, max_steps: int = DEFAULT_MAX_STEPS
) -> SessionDetail:
    """The detail of one session (records in step order); a longer one keeps its worst stretch."""
    codebase = Codebase(frozenset({records[0].project}))
    every = strip_of(records, codebase)
    _, shown = densest_window(every, max_steps)
    by_step = {record.step: record for record in records}
    digest = digest_of(records, codebase)
    return SessionDetail(
        goal=(digest.title or next(iter(digest.asks), "")) or None,
        date=digest.date if _ISO_DAY.match(digest.date) else None,
        minutes=_minutes(records),
        total=len(every),
        steps=shown,
        messages=_messages(shown, by_step),
        failed=_failures(shown, by_step),
        counts=_counts(every, by_step),
        shown_counts=_counts(shown, by_step),
    )


def _minutes(records: Sequence[Record]) -> int | None:
    stamps = [parsed for r in records if (parsed := _parsed(r.ts)) is not None]
    if len(stamps) < 2:
        return None
    stamps.sort()
    limit = ACTIVE_GAP_MINUTES * 60
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    return round(sum(gap for gap in gaps if gap <= limit) / 60)


def _parsed(stamp: str | None) -> datetime | None:
    """The stamp as a UTC-aware time, or None when it is not a real ISO time.

    Checked by pattern first so a bad stamp is "no time", not an exception caught and dropped.
    """
    found = _ISO_TIME.match(stamp or "")
    if not found or not _real_day(*(int(part) for part in found.groups()[:3])):
        return None
    parsed = datetime.fromisoformat(stamp or "")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _real_day(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]


def _messages(steps: Sequence[StripStep], by_step: dict[int, Record]) -> tuple[dict, ...]:
    out = []
    for index, step in enumerate(steps):
        if step.lane is not Lane.YOU or (said := typed_message(by_step[step.step])) is None:
            continue
        before = next((s for s in reversed(steps[:index]) if s.lane is not Lane.YOU), None)
        then = next((s for s in steps[index + 1 :] if s.lane is not Lane.YOU), None)
        out.append(
            {
                "step": step.step,
                "text": _line(said, MESSAGE_CHARS),
                "before": before.label[:NEIGHBOR_CHARS] if before else None,
                "then": then.label[:NEIGHBOR_CHARS] if then else None,
            }
        )
    return tuple(out)


def _failures(steps: Sequence[StripStep], by_step: dict[int, Record]) -> tuple[dict, ...]:
    return tuple(
        {
            "step": step.step,
            "command": _line(_working_command(by_step[step.step]), COMMAND_CHARS),
            "error": _line(_complaint(by_step[step.step].raw), ERROR_CHARS),
        }
        for step in steps
        if step.lane is Lane.FAILED
    )


def _working_command(record: Record) -> str:
    """The segment of the command that did the work, else the whole command."""
    command = record.command or ""
    program, args = program_words(command)
    return command if program == NO_PATH else " ".join((program, *args))


def _complaint(output: str) -> str:
    """The tool's own complaint line, else the last assertion or exception line, else nothing."""
    return raw_complaint(output) or next(iter(reversed(key_error_lines(output))), "")


def _line(text: str, limit: int) -> str:
    """One scrubbed line; scrubbed whole first so a cut cannot leave part of a secret."""
    return scrub(" ".join(text.split()))[:limit]


def _counts(steps: Sequence[StripStep], by_step: dict[int, Record]) -> dict[str, int]:
    lanes = [step.lane for step in steps]
    typed = sum(
        1
        for step in steps
        if step.lane is Lane.YOU and typed_message(by_step[step.step]) is not None
    )
    return {
        "steps": len(lanes),
        "failed": lanes.count(Lane.FAILED),
        "edits": lanes.count(Lane.CODE_EDIT),
        "scratch": lanes.count(Lane.SCRATCH_EDIT),
        "messages": typed,
        "passed": lanes.count(Lane.PASSED),
    }
