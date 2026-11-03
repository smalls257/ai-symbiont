"""The shapes of the requests the service takes: checked here, so a malformed one is a 400."""

import io
import json
import re
from typing import Any

from symbiont.miner.lesson_context import AppliesTo
from symbiont.records.schema import Record, RecordFormatError, load_jsonl
from symbiont.store.local import Source

MINE_KEYS = frozenset({"project", "sources"})


class BadRequestError(ValueError):
    """A request that does not have the shape its route takes."""


def spark_bound(request: dict[str, Any]) -> bool:
    """Absent means local; anything but a real bool is refused, never guessed."""
    value = request.get("spark_bound", False)
    if not isinstance(value, bool):
        raise BadRequestError("spark_bound must be true or false")
    return value


def hook_of(route: str, payload: Any) -> str:
    """The hook name to log: the event for observe, otherwise the route."""
    event = payload.get("event") if isinstance(payload, dict) else None
    return event if route == "observe" and isinstance(event, str) else route


def project_of(payload: Any) -> str:
    """The repository a request is about, for the event log; empty when it names none."""
    if not isinstance(payload, dict):
        return ""
    record = (payload.get("payload") or {}).get("record") if payload.get("event") else None
    named = record.get("project") if isinstance(record, dict) else payload.get("project")
    return named if isinstance(named, str) else ""


def as_object(payload: Any) -> dict[str, Any]:
    """The payload as a dict, or BadRequestError."""
    if not isinstance(payload, dict):
        raise BadRequestError("the request body must be a JSON object")
    return payload


def require_keys(
    request: dict[str, Any], allowed: frozenset[str], required: frozenset[str]
) -> None:
    """Raise BadRequestError for unexpected or missing request fields."""
    extra = sorted(set(request) - allowed)
    if extra:
        raise BadRequestError(f"unexpected fields: {', '.join(extra)}")
    missing = sorted(required - set(request))
    if missing:
        raise BadRequestError(f"missing fields: {', '.join(missing)}")


def observed(payload: Any) -> tuple[str, Record]:
    """The project and record carried by an observe payload."""
    body = as_object(payload)
    try:
        record = next(load_jsonl(io.StringIO(json.dumps(body.get("record")))))
    except (RecordFormatError, StopIteration) as exc:
        raise BadRequestError(f"payload.record is not a record: {exc}") from exc
    return record.project, record


def source_of(request: dict[str, Any]) -> Source:
    """The log source a learn request names; all three fields must be text."""
    reader, path, project = request["reader"], request["session_log_path"], request["project"]
    if not all(isinstance(value, str) for value in (reader, path, project)):
        raise BadRequestError("reader, session_log_path and project must be text")
    return Source(project, reader, path)


def mine_request_of(request: dict[str, Any]) -> tuple[str, list[Source]]:
    """The project and the logs a `/mine` request names (`sources`: [[reader, path], ...])."""
    require_keys(request, MINE_KEYS, MINE_KEYS)
    project, listed = request["project"], request["sources"]
    if not (isinstance(project, str) and isinstance(listed, list) and listed):
        raise BadRequestError("mine takes a project and a non-empty list of [reader, path] pairs")
    if not all(_is_text_pair(pair) for pair in listed):
        raise BadRequestError("every source must be a [reader, path] pair of text")
    return project, [Source(project, reader, path) for reader, path in listed]


def _is_text_pair(value: Any) -> bool:
    """A list of exactly two strings."""
    return isinstance(value, list) and len(value) == 2 and all(isinstance(x, str) for x in value)


def named_project(request: dict[str, Any]) -> str:
    """The repository a `/status` request names; any other shape is a 400."""
    require_keys(request, frozenset({"project"}), frozenset({"project"}))
    project = request["project"]
    if not isinstance(project, str):
        raise BadRequestError("project must be text")
    return project


_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def percent_decoded(text: str) -> str:
    """`text` with %XX escapes decoded (the stdlib decoder lives in a network module)."""
    return _PERCENT.sub(lambda hexed: chr(int(hexed[1], 16)), text.replace("+", " "))


MAX_TAGS = 30
MAX_TAG_CHARS = 60


def parse_applies(value: Any) -> AppliesTo:
    """`{terms: [...], areas: [...]}` as written by the session model or the dashboard."""
    if value is None:
        return AppliesTo()
    if not isinstance(value, dict) or not set(value) <= {"terms", "areas"}:
        raise BadRequestError("applies_to takes only terms and areas")
    return AppliesTo(_tags(value.get("terms", []), "terms"), _tags(value.get("areas", []), "areas"))


def _tags(value: Any, name: str) -> tuple[str, ...]:
    """A list of short strings, or BadRequestError naming the field."""
    ok = isinstance(value, list) and len(value) <= MAX_TAGS
    if not ok or not all(isinstance(tag, str) and 0 < len(tag) <= MAX_TAG_CHARS for tag in value):
        raise BadRequestError(f"applies_to.{name} must be a list of up to {MAX_TAGS} short strings")
    return tuple(tag.strip() for tag in value)
