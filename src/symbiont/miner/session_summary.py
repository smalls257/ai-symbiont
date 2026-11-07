"""One session's summary as the developer's own session model wrote it.

A summary with a 30-word goal or an invented outcome would reach the dashboard as if it were a
clean label, so every field is checked and a bad one raises `SummaryError` naming the field; the
service turns that into a resend message. Pure.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Word caps from the failure-cards plan (Task 8): a goal is a headline, a friction a short phrase.
MAX_GOAL_WORDS = 12
MAX_FRICTION_WORDS = 10


class SummaryOutcome(StrEnum):
    """How the session ended, as judged from its last turns."""

    DONE = "done"
    PARTLY = "partly"
    STUCK = "stuck"
    UNCLEAR = "unclear"


class SummaryError(ValueError):
    """A summary that does not have the shape the route takes; the message names the field."""


@dataclass(frozen=True)
class SessionSummary:
    """What a session was for, how it ended and what slowed it; noise marks a non-session."""

    session_id: str
    goal: str
    outcome: SummaryOutcome
    friction: str
    noise: bool


def summary_from(item: Mapping[str, Any]) -> SessionSummary:
    """A checked summary from a request item; raises SummaryError naming the bad field."""
    ident = _words(item, "session_id", 1)
    noise = item.get("noise", False)
    if not isinstance(noise, bool):
        raise SummaryError("noise must be true or false")
    return SessionSummary(
        ident,
        _words(item, "goal", MAX_GOAL_WORDS),
        _outcome(item.get("outcome")),
        _words(item, "friction", MAX_FRICTION_WORDS, required=False),
        noise,
    )


def _words(item: Mapping[str, Any], key: str, limit: int, *, required: bool = True) -> str:
    """A text field of at most `limit` words; empty only when `required` is False."""
    value = item.get(key, "")
    if not isinstance(value, str):
        raise SummaryError(f"{key} must be text")
    text = value.strip()
    if required and not text:
        raise SummaryError(f"{key} must be non-empty text")
    if len(text.split()) > limit:
        raise SummaryError(f"{key} must be at most {limit} words")
    return text


def _outcome(value: Any) -> SummaryOutcome:
    try:
        return SummaryOutcome(value)
    except ValueError as error:
        choices = ", ".join(member.value for member in SummaryOutcome)
        raise SummaryError(f"outcome must be one of: {choices}") from error
