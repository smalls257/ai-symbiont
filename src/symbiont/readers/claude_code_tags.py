"""What a Claude Code session was about, kept as record tags: its `ai-title` and each `gitBranch`.

Both are theme text for the Pain points stage. The title is written by a metadata event the reader
otherwise skips, so it is gathered while reading and given to the session's first user turn; the
branch rides on every event. A wrong shape raises like any other field.
"""

import re
from typing import Any

from symbiont.readers.claude_code_fields import MalformedError, optional_text, require_text
from symbiont.records.session_tags import branch_tag

TITLE_EVENT = "ai-title"
UNTITLED = "untitled session"
CORRECTION = "correction"
FAILURE_REPORT = "failure_report"
_TITLE_LENGTH = 80
# Claude Code writes a slash command as `<command-message>`/`<command-name>` markup and its output
# as `<local-command-...>`; a bare `/word` is one typed by hand. `/tmp/x` is a path, not a command.
_COMMAND_TURN = re.compile(r"^\s*(<command-|<local-command-|/[\w:-]+(\s|$))")
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
    """A title from a typed turn: its first line; None for command markup (it names no work)."""
    if _COMMAND_TURN.match(turn_text):
        return None
    first_line = turn_text.strip().splitlines()[0] if turn_text.strip() else ""
    return first_line[:_TITLE_LENGTH] or None


def remember_title(event: dict[str, Any], titles: dict[str, str]) -> None:
    """Keep the title an `ai-title` event gives its session; raises MalformedError."""
    titles[require_text(event, "sessionId")] = require_text(event, "aiTitle")


def branch_tags(event: dict[str, Any]) -> tuple[str, ...]:
    """The branch tag of one event, if it names a branch."""
    branch = optional_text(event, "gitBranch")
    return (branch_tag(branch),) if branch else ()


def session_title(session_id: str, titles: dict[str, str], typed: dict[str, str]) -> str:
    """The `ai-title`, else the first typed non-command turn, else "untitled session"."""
    return titles.get(session_id) or typed.get(session_id, UNTITLED)
