"""Lessons: a pain point that carries its own evidence, so no raw history needs keeping.

The store keeps lessons, never records: a lesson holds a short verbatim quote of
what happened, the steps that resolved it (in plain words), whether every record
it was built from may reach Spark, and the (session, step) ids it came from. The
records themselves are re-read from the harness's own logs whenever mining runs
and dropped afterwards. A lesson is training data for the personal model and is
deleted once training has consumed it.

The privacy flag is computed here, at mining time, from the source records;
it is never defaulted, because an unknown flag must not read as shareable.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from symbiont.miner.painpoint import PainPoint, RecordRef, Signal
from symbiont.miner.resolutions import Resolution, resolution_of
from symbiont.records.schema import Kind, Record

# Long enough for a command and the error line it ended on, short enough that a
# lesson is a citation, not a copy of the transcript.
QUOTE_CHARS = 240
# One resolution step names one command or one edited file and its first new line.
STEP_CHARS = 120
_CUT = "[...]"


@dataclass(frozen=True)
class Lesson:
    """One pain point with its own quote, resolution and privacy flag."""

    pain_point: PainPoint
    quote: str
    # What was done, step by step, in plain words; () when the history shows no fix.
    resolution: tuple[str, ...]
    # Why there is no resolution; None when there is one.
    unresolved_because: str | None
    spark_safe: bool
    # Every record the lesson quotes: the cited ones, then the resolution's steps.
    sources: tuple[RecordRef, ...]
    # Benchmark task ids of those records (none for the developer's own sessions); kept so
    # the record of what trained a model can still be checked against the hold-out.
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    """How many lessons of one signal have a resolution found in the history."""

    resolved: int
    total: int


def lessons_from(pain_points: Iterable[PainPoint], records: Sequence[Record]) -> list[Lesson]:
    """Build one lesson per pain point; `records` is the chain the pain points were mined from.

    Raises LookupError naming the reference when a cited record is missing:
    a lesson without its evidence would be a quote of nothing.
    """
    by_ref = {(r.session_id, r.step): r for r in records}
    return [_lesson(pain, _cited(pain, by_ref), records) for pain in pain_points]


def resolution_coverage(lessons: Iterable[Lesson]) -> dict[Signal, Coverage]:
    """Per signal, how many lessons have a resolution; every signal is listed, zeros included."""
    listed = list(lessons)
    totals = Counter(lesson.pain_point.signature.signal for lesson in listed)
    resolved = Counter(lesson.pain_point.signature.signal for lesson in listed if lesson.resolution)
    return {signal: Coverage(resolved[signal], totals[signal]) for signal in Signal}


def training_manifest(project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
    """What trained a model, as ids and counts only (no text), kept after the lessons are deleted.

    It is the hold-out evidence: a scored run checks that no task id here is held out.
    """
    entries = [
        {
            "session_id": lesson.pain_point.session_id,
            "step": lesson.pain_point.step,
            "signal": lesson.pain_point.signature.signal.value,
            "sources": [list(ref) for ref in lesson.sources],
            "task_ids": list(lesson.task_ids),
        }
        for lesson in lessons
    ]
    sessions = sorted({sid for lesson in lessons for sid, _ in lesson.sources})
    return {
        "project": project,
        "lessons": entries,
        "source_sessions": sessions,
        "counts": {"lessons": len(entries), "source_sessions": len(sessions)},
    }


def _cited(pain: PainPoint, by_ref: dict[RecordRef, Record]) -> list[Record]:
    missing = [ref for ref in pain.record_refs if ref not in by_ref]
    if missing:
        session_id, step = missing[0]
        raise LookupError(f"cited record {session_id}:{step} is not in the mined records")
    return [by_ref[ref] for ref in pain.record_refs]


def _lesson(pain: PainPoint, cited: list[Record], records: Sequence[Record]) -> Lesson:
    found = resolution_of(pain, cited, records)
    steps = found.steps if isinstance(found, Resolution) else ()
    used = [*cited, *steps]
    return Lesson(
        pain_point=pain,
        quote=excerpt(cited[0], QUOTE_CHARS),
        resolution=tuple(_step_words(step) for step in steps),
        unresolved_because=found if isinstance(found, str) else None,
        spark_safe=all(r.provenance.spark_safe for r in used),
        sources=tuple(dict.fromkeys((r.session_id, r.step) for r in used)),
        task_ids=tuple(dict.fromkeys(r.task_id for r in used if r.task_id is not None)),
    )


def excerpt(record: Record, limit: int) -> str:
    """A verbatim excerpt of at most `limit` characters.

    Command output keeps its end, where the error is; everything else keeps its start.
    """
    if record.kind in (Kind.COMMAND, Kind.TEST_RESULT):
        head = f"$ {record.command or ''}\n"
        return _clip_start(head, limit) + _clip_end(record.raw, limit - len(head))
    if record.kind == Kind.EDIT:
        return _clip_start(f"{', '.join(record.files)}\n{record.diff or record.raw}", limit)
    return _clip_start(record.raw, limit)


def _step_words(step: Record) -> str:
    if step.kind == Kind.COMMAND:
        return f"ran `{_clip_start(step.command or '', STEP_CHARS)}`"
    if step.kind == Kind.EDIT:
        return f"edited `{', '.join(step.files)}`{_first_new_line(step)}"
    return _clip_start(step.raw, STEP_CHARS)


def _first_new_line(edit: Record) -> str:
    for line in (edit.diff or "").splitlines():
        text = line[1:].strip()
        if line.startswith("+") and not line.startswith("+++") and text:
            return f" to add `{_clip_start(text, STEP_CHARS)}`"
    return ""


def _clip_start(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - len(_CUT), 0)] + _CUT


def _clip_end(text: str, limit: int) -> str:
    if len(text) <= max(limit, 0):
        return text
    if limit <= len(_CUT):
        return ""
    return _CUT + text[len(text) - (limit - len(_CUT)) :]
