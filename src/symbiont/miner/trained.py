"""What trained a model: lesson ids, export ids, the manifest, and the hold-out check on lessons.

Lessons are deleted once a model has been trained on them; the manifest keeps
their ids, source sessions and task ids (never text), so a scored run can still
prove no held-out trajectory trained the model. Pure: lessons in, ids out.
"""

import hashlib
from collections.abc import Iterable, Sequence

from symbiont.miner.lessons import Lesson
from symbiont.records.holdout import HoldOutViolationError, normalise_task_id

# Long enough that two different exports never share an id in practice.
_EXPORT_ID_CHARS = 16


def lesson_id(lesson: Lesson) -> str:
    """Where the lesson's pain point sits and what kind it is; no text."""
    pain = lesson.pain_point
    return f"{pain.session_id}:{pain.step}:{pain.signature.signal.value}"


def export_id_of(lessons: Iterable[Lesson]) -> str:
    """A stable id for one set of exported lessons, whatever their order."""
    joined = "\n".join(sorted(lesson_id(lesson) for lesson in lessons))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_EXPORT_ID_CHARS]


def training_manifest(project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
    """What trained a model, as ids and counts only (no text), kept after the lessons are deleted.

    It is the hold-out evidence: a scored run checks that no task id here is held out.
    """
    entries = [
        {
            "lesson_id": lesson_id(lesson),
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
        "export_id": export_id_of(lessons),
        "lessons": entries,
        "source_sessions": sessions,
        "counts": {"lessons": len(entries), "source_sessions": len(sessions)},
    }


def refuse_held_out_lessons(lessons: Iterable[Lesson], held_out_tasks: frozenset[str]) -> None:
    """Raise HoldOutViolationError for the first lesson quoting a held-out task's records."""
    held = {normalise_task_id(t) for t in held_out_tasks}
    if not held:
        return
    for lesson in lessons:
        for task_id in lesson.task_ids:
            if normalise_task_id(task_id) in held:
                raise HoldOutViolationError(task_id, lesson.pain_point.session_id)
