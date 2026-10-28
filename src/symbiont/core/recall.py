"""Recall: which stored lessons answer a plain question."""

import re
from collections.abc import Iterable

from symbiont.miner.lessons import Lesson

DEFAULT_LIMIT = 2
_WORD = re.compile(r"[a-z0-9_]{3,}")


def relevant_lessons(
    question: str, lessons: Iterable[Lesson], *, limit: int = DEFAULT_LIMIT
) -> list[Lesson]:
    """Lessons whose trouble, quote or fix share words with the question, best first."""
    wanted = set(_WORD.findall(question.lower()))
    scored = [(len(wanted & _lesson_words(lesson)), lesson) for lesson in lessons]
    hits = [(score, lesson) for score, lesson in scored if score > 0]
    hits.sort(key=lambda hit: (-hit[0], hit[1].pain_point.session_id, hit[1].pain_point.step))
    return [lesson for _, lesson in hits[:limit]]


def _lesson_words(lesson: Lesson) -> set[str]:
    """Lowercase words of a lesson's trouble, quote and fix."""
    text = " ".join([*lesson.pain_point.signature.key, lesson.quote, *lesson.resolution])
    return set(_WORD.findall(text.lower()))
