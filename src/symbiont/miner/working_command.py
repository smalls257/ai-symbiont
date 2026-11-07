"""The command an agent ran, as the one short line a person recognizes it by.

An example line on the Inbox shows the working command, not the `cd dir &&` before it, the
heredoc a commit message was fed through or the message itself. Pure: text in, text out.
"""

import re

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.shell_text import shell_text

# One line of an Inbox row; longer and the row wraps into a wall of text.
LINE_CHARS = 100
_LEADING_CD = re.compile(r"^\s*cd\s+\S+\s*&&\s*")
_MESSAGE = re.compile(
    r"(?P<flag>(?:-m|--message)(?:\s+|=))"
    r"(?:\"\$\(.*|\"(?:[^\"\\]|\\.)*\"|'[^']*')",
    re.S,
)
_CUT = "…"


def working_command(command: str) -> str:
    """The command on one line, at most LINE_CHARS: no `cd X &&`, heredoc or message body."""
    bare = _LEADING_CD.sub("", command)
    bare = _MESSAGE.sub(lambda found: found["flag"].rstrip("= ") + " " + _CUT, bare)
    line = scrub(shell_text(bare).strip()).split(" ; ")[0].strip()
    return line if len(line) <= LINE_CHARS else line[: LINE_CHARS - 1].rstrip() + _CUT
