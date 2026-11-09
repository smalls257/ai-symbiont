"""Field validators for the Claude Code reader; a wrong shape raises MalformedError."""

from typing import Any


class MalformedError(Exception):
    """Internal: an event is not in the shape this reader knows. Becomes a ReadError."""


class RefusedCallError(Exception):
    """Internal: the tool would reject this call's input (the agent's mistake, not a bad file)."""


def require(mapping: Any, key: str) -> Any:
    """The mapping's value for `key`; a missing or null one raises MalformedError."""
    if not isinstance(mapping, dict) or mapping.get(key) is None:
        raise MalformedError(f"missing {key!r}")
    return mapping[key]


def require_str(value: Any, field: str) -> str:
    """The value if it is a string, else MalformedError naming the field."""
    if not isinstance(value, str):
        raise MalformedError(f"{field!r} must be a string, got {type(value).__name__}")
    return value


def require_text(mapping: Any, key: str) -> str:
    """The string under `key` in the mapping; missing or non-string raises MalformedError."""
    return require_str(require(mapping, key), key)


def optional_text(mapping: dict[str, Any], key: str) -> str:
    """A field the harness may omit; empty then, but never a non-string."""
    value = mapping.get(key)
    return "" if value is None else require_str(value, key)


def origin_kind(event: dict[str, Any]) -> str | None:
    """The `origin.kind` Claude Code stamps on events; None in older logs."""
    origin = event.get("origin")
    if origin is None:
        return None
    if not isinstance(origin, dict):
        raise MalformedError(f"'origin' must be an object, got {type(origin).__name__}")
    return require_text(origin, "kind")
