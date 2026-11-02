"""POST /lessons/<id>/context: the developer's words about one lesson (the dashboard's payload).

Payload: {text, intentional, priority, applies_to}; `project`, if given, must match.
"""

from typing import Any

from symbiont.miner.lesson_context import LessonContext, Priority
from symbiont.service.request_shapes import (
    BadRequestError,
    parse_applies,
    percent_decoded,
    require_keys,
)
from symbiont.store.local import Store

FIELDS = frozenset({"text", "intentional", "priority", "project", "applies_to"})
MAX_TEXT_CHARS = 2000


class UnknownLessonError(LookupError):
    """No stored lesson has the id in the path."""


def context_target(route: str) -> str | None:
    """The lesson id of a `lessons/<id>/context` route, else None."""
    parts = route.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "lessons" and parts[2] == "context" and parts[1]:
        return percent_decoded(parts[1])
    return None


def save_context(store: Store, lesson_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Store the words for a lesson; raises UnknownLessonError or BadRequestError."""
    require_keys(request, FIELDS, frozenset({"text"}))
    context = _context_of(request)
    found = store.catalog.find(lesson_id)
    if found is None or request.get("project", found[0]) != found[0]:
        raise UnknownLessonError(f"no lesson {lesson_id}")
    store.contexts.save(lesson_id, found[0], context)
    return {"lesson": lesson_id, "project": found[0]}


def _context_of(request: dict[str, Any]) -> LessonContext:
    """The words, the intentional flag and the priority from a request, or BadRequestError."""
    text, intentional = request["text"], request.get("intentional", False)
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise BadRequestError(f"text must be a string of at most {MAX_TEXT_CHARS} characters")
    if not isinstance(intentional, bool):
        raise BadRequestError("intentional must be true or false")
    try:
        priority = Priority(request.get("priority", Priority.NORMAL))
    except ValueError as exc:
        raise BadRequestError("priority must be low, normal or high") from exc
    return LessonContext(
        text.strip(), intentional, priority, parse_applies(request.get("applies_to"))
    )
