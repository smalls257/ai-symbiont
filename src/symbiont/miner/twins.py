"""Twin lessons: the same trouble met again, merged so one lesson lists every fix tried.

Plug round 4 scored its rule on lessons where a failed command with the same error line was one
lesson (prereg/2026-10-29-plug-round4-DRAFT.md, "twins"). Without the merge a recurrence would
show the first twin's single fix and hide the others.
"""

from dataclasses import replace

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal


def merge_twins(lessons: list[Lesson]) -> list[Lesson]:
    """One lesson per failed command and error line, fixes pooled, first-seen order."""
    firsts: dict[tuple[str, ...], int] = {}
    merged: list[Lesson] = []
    for lesson in lessons:
        signature = lesson.pain_point.signature
        if signature.signal is not Signal.FAILED_COMMAND:
            merged.append(lesson)
        elif signature.key in firsts:
            slot = firsts[signature.key]
            merged[slot] = _pooled(merged[slot], lesson)
        else:
            firsts[signature.key] = len(merged)
            merged.append(lesson)
    return merged


def _pooled(kept: Lesson, twin: Lesson) -> Lesson:
    """`kept` with the twin's fixes, sources, task ids and privacy folded in."""
    resolution = _union(kept.resolution, twin.resolution)
    return replace(
        kept,
        resolution=resolution,
        sources=_union(kept.sources, twin.sources),
        task_ids=_union(kept.task_ids, twin.task_ids),
        changed_alongside=_union(kept.changed_alongside, twin.changed_alongside),
        private_datasets=_union(kept.private_datasets, twin.private_datasets),
        spark_safe=kept.spark_safe and twin.spark_safe,
        unresolved_because=None if resolution else kept.unresolved_because,
    )


def _union(first: tuple, second: tuple) -> tuple:
    """Both tuples' items, first-seen order, no repeats."""
    return tuple(dict.fromkeys((*first, *second)))
