"""What a Claude Code session was about, kept as record tags: its `ai-title` and each `gitBranch`.

Both are theme text for the Pain points stage. The title is written by a metadata event the reader
otherwise skips, so it is gathered while reading and given to the session's first user turn; the
branch rides on every event. A wrong shape raises like any other field.
"""

from typing import Any

from symbiont.readers.claude_code_fields import optional_text, require_text
from symbiont.records.session_tags import branch_tag, title_tag

TITLE_EVENT = "ai-title"


def remember_title(event: dict[str, Any], titles: dict[str, str]) -> None:
    """Keep the title an `ai-title` event gives its session; raises MalformedError."""
    titles[require_text(event, "sessionId")] = require_text(event, "aiTitle")


class EventTags:
    """The tags each event's records carry: its branch, and once per session its title."""

    def __init__(self, titles: dict[str, str]):
        """Start with the titles the file gave its sessions."""
        self._titles = titles
        self._given: set[str] = set()

    def of(
        self, event: dict[str, Any], session_id: str, *, first_user_turn: bool
    ) -> tuple[str, ...]:
        """The branch tag, then the title tag when this is the session's first user turn."""
        branch = optional_text(event, "gitBranch")
        tags: tuple[str, ...] = (branch_tag(branch),) if branch else ()
        title = self._titles.get(session_id)
        if first_user_turn and title and session_id not in self._given:
            self._given.add(session_id)
            tags += (title_tag(title),)
        return tags
