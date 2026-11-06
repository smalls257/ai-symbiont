"""One mined pain point as the session's model reads it when it judges whether it is noise.

It carries the command, the failing lines, the fix (or what changed alongside), the files and the
developer's own words, so the reviewer can see what broke and how it ended. Plain prose, no scores.
"""

from collections.abc import Sequence
from typing import Any

from symbiont.core.failure_signature import failure_detail
from symbiont.core.notes import happened, resolution_clause
from symbiont.miner.lesson_context import LessonContext
from symbiont.miner.lessons import Lesson
from symbiont.miner.secrets import scrub
from symbiont.miner.trained import lesson_id
from symbiont.service.candidate_summary import outcome_sentence
from symbiont.service.dashboard_view import command_of_signature


def review_candidate(
    lesson: Lesson, words: LessonContext | None, same_trouble: Sequence[Lesson] = ()
) -> dict[str, Any]:
    """The lesson's candidate object; `words` is what the developer already said about it.

    `same_trouble` is every stored lesson of the same kind of trouble, this one included, so the
    reviewer can see how often it happened; empty counts the lesson alone.
    """
    signature = lesson.pain_point.signature
    errors = [scrub(line) for line in lesson.error_lines]
    candidate: dict[str, Any] = {
        "id": lesson_id(lesson),
        "kind": signature.signal.value,
        "what_happened": happened(signature),
        "command": command_of_signature(signature),
        "error": scrub(failure_detail(lesson.quote)) or (errors[-1] if errors else ""),
        "error_lines": errors,
        "fix": _fix(lesson),
        "fix_steps": list(lesson.resolution),
        "also_changed": list(lesson.changed_alongside),
        "files": list(lesson.files),
        "context": scrub(lesson.quote[:200]),
        "asked": scrub(lesson.asked),
        "agent_intent": scrub(lesson.agent_intent),
        "times_it_happened": max(len(same_trouble), 1),
        "sessions_it_happened_in": _sessions(lesson, same_trouble),
        "outcome": scrub(outcome_sentence(lesson)),
    }
    if words is not None:
        candidate["developer_said"] = scrub(words.text)
        candidate["developer_priority"] = words.priority.value
        candidate["developer_marked_intentional"] = words.intentional
    return candidate


def _fix(lesson: Lesson) -> str | None:
    """How it was fixed; else what changed between the failure and the later pass, said as such.

    An edit to a file the failure never names is not claimed as the fix, but a reviewer judging
    "noise" must still see that something was edited before the command passed.
    """
    if lesson.resolution:
        return resolution_clause(lesson)
    if lesson.changed_alongside:
        return "no confirmed fix; before it passed you " + ", then ".join(lesson.changed_alongside)
    return None


def _sessions(lesson: Lesson, same_trouble: Sequence[Lesson]) -> int:
    """How many distinct sessions the trouble showed up in."""
    seen = {item.pain_point.session_id for item in same_trouble}
    return len(seen | {lesson.pain_point.session_id})
