"""The line a failing tool printed to say what is wrong, as printed, without its advice lines.

`tool_messages.raw_complaint` finds the last complaint, but git ends a failure with hints
("remove the file manually to continue.") that are advice, not the complaint. Pure: text in,
one scrubbed line out, "" when the tool printed none.
"""

import re

from symbiont.miner.tool_messages import raw_complaint

COMPLAINT_CHARS = 160
# Advice and trailers that follow the real complaint: git hints, npm's log pointer.
HINT_LINE = re.compile(
    r"^\s*(?:hint:|npm notice|npm ERR! A complete log|A complete log of this run)"
    r"|remove the file manually|If no other git process|^\s*Another git process",
    re.IGNORECASE,
)


def complaint_of(output: str) -> str:
    """The tool's own complaint line from the whole output, at most COMPLAINT_CHARS."""
    kept = [line for line in output.splitlines() if not HINT_LINE.search(line)]
    line = raw_complaint("\n".join(kept)) or ""
    flat = " ".join(line.split())
    return flat if len(flat) <= COMPLAINT_CHARS else flat[: COMPLAINT_CHARS - 1].rstrip() + "…"
