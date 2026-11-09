"""A slash command as the developer typed it, not the markup Claude Code wraps it in.

`<command-name>/review</command-name><command-args>pr 12</command-args>` reads `/review pr 12`.
Pure: text in, text out.
"""

import re

_COMMAND_NAME = re.compile(r"<command-name>\s*([^<\s]+)\s*</command-name>")
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


def typed_text(raw: str) -> str:
    """The slash command and its arguments when `raw` is one, else `raw` unchanged."""
    named = _COMMAND_NAME.search(raw)
    if not named:
        return raw
    args = _COMMAND_ARGS.search(raw)
    return " ".join((named.group(1), *(args.group(1).split() if args else ())))
