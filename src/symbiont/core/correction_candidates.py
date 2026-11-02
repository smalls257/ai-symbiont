"""Candidate corrections: user turns that look like the developer correcting the agent.

Rules pre-filter so the session's model reads a few hundred short excerpts, not whole histories:
a short user turn that follows something the agent did and uses a correcting phrase. The model
makes the real judgment; this only decides what is worth showing. Pure: records in, excerpts out.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG
from symbiont.records.schema import Kind, Record

CAP = 200
MAX_TURN_CHARS = 280
EXCERPT_CHARS = 240
ACTION_CHARS = 70
SAID_CHARS = 200
_CUES = re.compile(
    r"\b(?:no|not|don'?t|do not|wrong|instead|stop|revert|undo|shouldn'?t|should not|actually|"
    r"i said|why did you|never|again|that'?s not|supposed to|should be|rather)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    """A user turn worth judging, with what the agent had just done."""

    candidate_id: str
    excerpt: str
    after: str
    files: tuple[str, ...] = ()
    agent_said: str = ""


def correction_candidates(records: Sequence[Record], cap: int = CAP) -> list[Candidate]:
    """The newest `cap` candidates, oldest first; `candidate_id` is `session:step`."""
    found: list[Candidate] = []
    previous: Record | None = None
    for record in records:
        if previous is not None and previous.session_id != record.session_id:
            previous = None
        if _is_candidate(record, previous):
            found.append(
                Candidate(
                    f"{record.session_id}:{record.step}",
                    _trim(record.raw, EXCERPT_CHARS),
                    _after(previous),
                    previous.files if previous else (),
                    _said(previous),
                )
            )
        previous = record
    return found[-cap:]


def _is_candidate(record: Record, previous: Record | None) -> bool:
    """A short, untagged user turn after an agent action that uses a correcting phrase."""
    if record.kind is not Kind.USER_TURN or previous is None or previous.kind is Kind.USER_TURN:
        return False
    if OUR_OUTPUT_RECORD_TAG in record.tags or len(record.raw) > MAX_TURN_CHARS:
        return False
    return _CUES.search(record.raw) is not None


def _after(previous: Record | None) -> str:
    """A few words for what the agent had just done."""
    if previous is None:
        return ""
    if previous.kind is Kind.COMMAND:
        return f"ran `{_trim(previous.command or '', ACTION_CHARS)}`"
    if previous.kind is Kind.EDIT and previous.files:
        return f"edited `{previous.files[0]}`"
    return _trim(f"{previous.kind.value}: {previous.raw}", ACTION_CHARS)


def _said(previous: Record | None) -> str:
    """What the agent had just told the developer, or the command output it was reacting to."""
    if previous is None or previous.kind not in (Kind.AGENT_TURN, Kind.COMMAND):
        return ""
    return _trim(previous.raw, SAID_CHARS)


def _trim(text: str, limit: int) -> str:
    """`text` on one line, cut to `limit` characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."
