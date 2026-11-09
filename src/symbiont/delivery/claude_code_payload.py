"""Claude Code's hook payload quirks, kept out of the shared hook code.

Claude Code's PostToolUse for a shell command carries no
exit code (a success was recorded as "unknown"), and a user interrupt arrives as a failure with
`is_interrupt: true` (it was recorded as a failed command). Muse Code's payloads differ, so
`hooks.py` calls this only when the harness is Claude Code.
"""

import re
from typing import Any

_EXIT_CODE_LINE = re.compile(r"^Exit code (-?\d+)")


def shell_exit_code(data: dict[str, Any], raw: str, *, failed: bool) -> int | None:
    """The exit status of a Claude Code shell call; None when the user interrupted it.

    A failure prints "Exit code N" first; a failure without that line is 1. A success with no
    reported code is 0, because Claude Code only fires PostToolUse for a call that finished.
    """
    if data.get("is_interrupt") is True or _interrupted(data.get("tool_response")):
        return None
    if not failed:
        return 0  # a stdout that happens to start with "Exit code" is not a status
    found = _EXIT_CODE_LINE.match(raw)
    return int(found.group(1)) if found else 1


def _interrupted(response: Any) -> bool:
    """Whether the Bash tool response says the user stopped the command."""
    return isinstance(response, dict) and response.get("interrupted") is True
