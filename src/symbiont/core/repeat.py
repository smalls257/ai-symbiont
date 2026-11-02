"""The exact-repeat rule: a new repository gets a note on day one.

The same command failing the same way as a stored failure is told what was done last time. "The
same way" is the normalized failure signature (test and message), never just the command and the
exception class. It reuses the miner's failed-command finder, so a planned failure (a TDD red)
is never a repeat. Pure: records and lessons in, one sentence out.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.core.failure_signature import failure_detail, same_failure
from symbiont.core.notes import check_to_run, happened, resolution_clause
from symbiont.miner.lesson_context import LessonContext
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.miner.trained import lesson_id
from symbiont.records.schema import Kind, Record

LEAD = "[symbiont] In this repo: "
CONTEXT_CHARS = 300


@dataclass(frozen=True)
class RepeatNote:
    """A sentence for the agent and the stored lesson it rests on."""

    sentence: str
    lesson: Lesson
    # Why it spoke: the same failure signature, or which relevance match brought a rule.
    why: str = "same failure signature"


def failed_now(record: Record) -> bool:
    """Whether this record is a command that failed; a pass or an unreported status is not."""
    return record.kind is Kind.COMMAND and record.exit_code not in (None, 0)


def repeat_note(
    failed: Record,
    earlier: Sequence[Record],
    lessons: Sequence[Lesson],
    contexts: Mapping[str, LessonContext] | None = None,
) -> RepeatNote | None:
    """The note for `failed` when a stored lesson has its exact failure signature, else None.

    `earlier` is the session so far; it tells a planned failure from a mistake. A lesson the
    developer marked intentional never speaks; one with no fix speaks only if they added words.
    """
    current = _failure_signature(failed, earlier)
    if current is None:
        return None
    wanted = contexts or {}
    matching = [
        lesson
        for lesson in lessons
        if lesson.pain_point.signature == current
        and same_failure(failed.raw, lesson.quote)
        and not _intentional(wanted.get(lesson_id(lesson)))
        and (lesson.resolution or wanted.get(lesson_id(lesson)))
    ]
    if not matching:
        return None
    lesson = sorted(matching, key=lambda item: bool(item.resolution))[-1]
    return RepeatNote(_sentence(lesson, wanted.get(lesson_id(lesson))), lesson)


def _intentional(context: LessonContext | None) -> bool:
    """Whether the developer said this failure is on purpose."""
    return context is not None and context.intentional


def _failure_signature(failed: Record, earlier: Sequence[Record]) -> Signature | None:
    """The failed-command signature of `failed`, or None for a pass or a planned failure."""
    session = [*earlier, failed]
    for pain in find_failed_commands(session):
        same_place = (pain.session_id, pain.step) == (failed.session_id, failed.step)
        if same_place and pain.signature.signal is Signal.FAILED_COMMAND:
            return pain.signature
    return None


def _sentence(lesson: Lesson, context: LessonContext | None) -> str:
    """Last time, what failed; how it was fixed; the check to run. Their words lead if given."""
    signature = lesson.pain_point.signature
    detail = failure_detail(lesson.quote).removeprefix(f"{signature.key[-1]}: ")
    failed = happened(signature) + (f" ({detail})" if detail else "")
    if lesson.resolution:
        body = (
            f"Last time, {failed}; it was fixed when {resolution_clause(lesson)}. "
            f"Check: {check_to_run(signature)}."
        )
    else:
        body = f"Last time, {failed}; no fix was found in the history."
    if context is None or not context.text.strip():
        return body
    words = context.text.strip()[:CONTEXT_CHARS].rstrip(" .")
    return f"{LEAD}{words}. {body}"
