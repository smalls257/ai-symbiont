"""What a Claude Code session was about, kept as record tags: its `ai-title` and each `gitBranch`.

Both are theme text for the Pain points stage. The title is written by a metadata event the reader
otherwise skips, so it is gathered while reading and given to the session's first user turn; the
branch rides on every event. A wrong shape raises like any other field.
"""

import re
from typing import Any

from symbiont.readers.claude_code_fields import MalformedError, optional_text, require_text
from symbiont.records.session_tags import branch_tag, title_tag

TITLE_EVENT = "ai-title"
UNTITLED = "untitled session"
CORRECTION = "correction"
FAILURE_REPORT = "failure_report"
_TITLE_LENGTH = 80
_SLASH_COMMAND = re.compile(r"^\s*(<command-name>|/[\w:.-]+(\s|$))")
# SWE-chat labels a pushback turn; "non_pushback" is its label for a turn that is NOT one.
_PUSHBACK_TAGS = {
    "correction": CORRECTION,
    "rejection": CORRECTION,
    "failure_report": FAILURE_REPORT,
    "non_pushback": None,
    "": None,
}


def pushback_tags(event: dict[str, Any]) -> tuple[str, ...]:
    """The tag SWE-chat's `prompt_pushback` label stands for; an unknown label raises."""
    flag = event.get("prompt_pushback")
    if flag is None or flag is False:
        return ()
    if flag is True:
        return (CORRECTION,)
    if isinstance(flag, str) and flag in _PUSHBACK_TAGS:
        tag = _PUSHBACK_TAGS[flag]
        return () if tag is None else (tag,)
    raise MalformedError(f"prompt_pushback must be true/false or a known label, got {flag!r}")


def fallback_title(turn_text: str) -> str | None:
    """A title from a typed turn: its first line; None for a slash command (it names no work)."""
    if _SLASH_COMMAND.match(turn_text):
        return None
    first_line = turn_text.strip().splitlines()[0] if turn_text.strip() else ""
    return first_line[:_TITLE_LENGTH] or None


def remember_title(event: dict[str, Any], titles: dict[str, str]) -> None:
    """Keep the title an `ai-title` event gives its session; raises MalformedError."""
    titles[require_text(event, "sessionId")] = require_text(event, "aiTitle")


class EventTags:
    """The tags each event's records carry: its branch, and once per session its title."""

    def __init__(self, titles: dict[str, str], fallback_titles: dict[str, str]):
        """Start with the `ai-title` titles, and the first typed turn of each session."""
        self._titles = titles
        self._fallbacks = fallback_titles
        self._given: set[str] = set()

    def of(
        self, event: dict[str, Any], session_id: str, *, first_user_turn: bool
    ) -> tuple[str, ...]:
        """The branch tag, then the title tag when this is the session's first user turn."""
        branch = optional_text(event, "gitBranch")
        tags: tuple[str, ...] = (branch_tag(branch),) if branch else ()
        if first_user_turn and session_id not in self._given:
            title = self._titles.get(session_id) or self._fallbacks.get(session_id, UNTITLED)
            self._given.add(session_id)
            tags += (title_tag(title),)
        return tags
