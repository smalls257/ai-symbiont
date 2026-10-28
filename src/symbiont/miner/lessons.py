"""Lessons: a pain point that carries its own evidence, so no raw history needs keeping.

A lesson holds a short verbatim quote, the steps that resolved it in plain words, whether every
record it came from may reach Spark, and the (session, step) ids it came from. The flag is
computed here from the source records and never defaulted: an unknown flag must not read as
shareable. A lesson is training data for the personal model, deleted once training has consumed
it.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from symbiont.miner.painpoint import PainPoint, RecordRef, Signal
from symbiont.miner.resolutions import Resolution, Unresolved, resolution_of
from symbiont.records.privacy import OwnHistoryConsent, is_own_history
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
    # Changes made between a failure and its pass that the failure never pointed at,
    # in plain words: said to have happened, never claimed as the fix.
    changed_alongside: tuple[str, ...] = ()
    # Datasets of the quoted records that are not Spark-safe; () when spark_safe. A private
    # lesson with none named counts as third-party (unknown privacy is never shareable).
    private_datasets: tuple[str, ...] = ()


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


def _cited(pain: PainPoint, by_ref: dict[RecordRef, Record]) -> list[Record]:
    """The records a pain point cites; a missing one raises LookupError."""
    missing = [ref for ref in pain.record_refs if ref not in by_ref]
    if missing:
        session_id, step = missing[0]
        raise LookupError(f"cited record {session_id}:{step} is not in the mined records")
    return [by_ref[ref] for ref in pain.record_refs]


def _lesson(pain: PainPoint, cited: list[Record], records: Sequence[Record]) -> Lesson:
    """One lesson: the pain point, its resolution and the quote it carries."""
    found = resolution_of(pain, cited, records)
    steps = found.steps if isinstance(found, Resolution) else ()
    alongside = found.alongside if isinstance(found, Resolution | Unresolved) else ()
    used = [*cited, *alongside, *steps]
    return Lesson(
        pain_point=pain,
        quote=excerpt(cited[0], QUOTE_CHARS),
        resolution=tuple(_step_words(step) for step in steps),
        unresolved_because=found if isinstance(found, str) else None,
        spark_safe=all(r.provenance.spark_safe for r in used),
        sources=tuple(dict.fromkeys((r.session_id, r.step) for r in used)),
        task_ids=tuple(dict.fromkeys(r.task_id for r in used if r.task_id is not None)),
        changed_alongside=tuple(_step_words(step) for step in alongside),
        private_datasets=_private_datasets(used),
    )


def _private_datasets(used: Sequence[Record]) -> tuple[str, ...]:
    """Names of the datasets among `used` that are not Spark-safe."""
    return tuple(sorted({r.provenance.dataset for r in used if not r.provenance.spark_safe}))


def spark_allowed(lesson: Lesson, consent: OwnHistoryConsent) -> bool:
    """Whether the lesson may back a Spark-bound answer.

    Spark-safe lessons may. A private one may only with the user's consent and only when every
    private record it quotes is the user's own session; third-party data never may.
    """
    if lesson.spark_safe:
        return True
    if consent is not OwnHistoryConsent.GIVEN or not lesson.private_datasets:
        return False
    return all(is_own_history(dataset) for dataset in lesson.private_datasets)


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
    """A resolving step in plain words."""
    if step.kind == Kind.COMMAND:
        return f"ran `{_clip_start(step.command or '', STEP_CHARS)}`"
    if step.kind == Kind.EDIT:
        return f"edited `{', '.join(step.files)}`{_first_new_line(step)}"
    return _clip_start(step.raw, STEP_CHARS)


def _first_new_line(edit: Record) -> str:
    """` to add <first added line>` for an edit, empty when it adds nothing."""
    for line in (edit.diff or "").splitlines():
        text = line[1:].strip()
        if line.startswith("+") and not line.startswith("+++") and text:
            return f" to add `{_clip_start(text, STEP_CHARS)}`"
    return ""


def _clip_start(text: str, limit: int) -> str:
    """The text cut to `limit`, keeping its start."""
    if len(text) <= limit:
        return text
    return text[: max(limit - len(_CUT), 0)] + _CUT


def _clip_end(text: str, limit: int) -> str:
    """The text cut to `limit`, keeping its end."""
    if len(text) <= max(limit, 0):
        return text
    if limit <= len(_CUT):
        return ""
    return _CUT + text[len(text) - (limit - len(_CUT)) :]
