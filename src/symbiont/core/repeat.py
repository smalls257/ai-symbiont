"""The exact-repeat rule: a new repository gets a note on day one.

The same command failing the same normalized way as a stored failure that was later fixed is
told how it was fixed. It reuses the miner's failed-command finder, so a planned failure (a TDD
red) is never a repeat. Pure: records and lessons in, one sentence out.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.notes import check_to_run, happened, resolution_clause
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.records.schema import Record


@dataclass(frozen=True)
class RepeatNote:
    """A sentence for the agent and the stored lesson it rests on."""

    sentence: str
    lesson: Lesson


def repeat_note(
    failed: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
) -> RepeatNote | None:
    """The note for `failed` when a stored, fixed failure has its exact signature, else None.

    `earlier` is the session so far; it tells a planned failure from a mistake.
    """
    current = _failure_signature(failed, earlier)
    if current is None:
        return None
    fixed = [
        lesson for lesson in lessons if lesson.pain_point.signature == current and lesson.resolution
    ]
    if not fixed:
        return None
    lesson = fixed[-1]
    return RepeatNote(_sentence(lesson), lesson)


def _failure_signature(failed: Record, earlier: Sequence[Record]) -> Signature | None:
    """The failed-command signature of `failed`, or None for a pass or a planned failure."""
    session = [*earlier, failed]
    for pain in find_failed_commands(session):
        same_place = (pain.session_id, pain.step) == (failed.session_id, failed.step)
        if same_place and pain.signature.signal is Signal.FAILED_COMMAND:
            return pain.signature
    return None


def _sentence(lesson: Lesson) -> str:
    """Last time, what failed; how it was fixed; the check to run."""
    signature = lesson.pain_point.signature
    return (
        f"Last time, {happened(signature)}; it was fixed when {resolution_clause(lesson)}. "
        f"Check: {check_to_run(signature)}."
    )
