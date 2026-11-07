"""The complaint a failing tool printed, normalized so the same complaint groups together.

Pure: text in, text out. Numbers, paths, URLs, hashes and quoted names become placeholders;
`failure_keys.broke_in_words` turns them back into prose for notes.
"""

import re

from symbiont.miner.credential_patterns import scrub

# Long enough for the longest TypeScript message seen (about 99 characters once normalized).
MESSAGE_CHARS = 120
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_EVAL_PREFIX = re.compile(r"^\(eval\):\d+:\s*")
_TOOL_PREFIX = re.compile(r"^[\w.-]+:\s+")
_TYPESCRIPT_ERROR = re.compile(r"error TS\d+:.*")
_COMPLAINT_START = re.compile(r"^(?:(?:fatal|error|Error|ERROR)[: ]|husky - )")

# What git, gh, pnpm, npm, zsh and the harness print when a command fails, read from real
# failures (failure-cards plan, 2026-11-07 measurement).
COMPLAINT_MARKERS = (
    r"ERR_[A-Z_]+",
    r"No such file or directory",
    r"command not found",
    r"Permission denied",
    r"no matches found",
    r"not found",
    r"HTTP \d{3}",
    r"Could not resolve",
    r"rate limit",
    r"timed out",
    r"failed to parse",
    r"is already used by",
    r"rejected",
)
_COMPLAINT_ANYWHERE = re.compile("|".join(COMPLAINT_MARKERS))

_URL = re.compile(r"""https?://[^\s'"`)]+""")
_QUOTED = re.compile(r"""(?:(?<=\s)|(?<=[(:])|^)(?:'[^']*'|"[^"]*"|`[^`]*`)""")
_PATH = re.compile(r"\S*/\S*")
_HASH = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
_DURATION_PART = r"\d+(?:\.\d+)?(?:ms|[smh])\b"
_DURATION = re.compile(rf"{_DURATION_PART}(?:\s+{_DURATION_PART})*")
_PARTIAL_PLACEHOLDER = re.compile(r"<[a-z]*$")
_NUMBER = re.compile(r"(?<!HTTP )\b\d+(?:\.\d+)?\b")


def tool_message(output: str) -> str | None:
    """The normalized last complaint line of a tool's output, or None when it printed none.

    Credentials are scrubbed first: the line becomes part of a group name.
    """
    text = scrub(_ANSI.sub("", output))
    typescript = _TYPESCRIPT_ERROR.findall(text)
    if typescript:
        return _normalized(typescript[-1])
    complaints = [line for line in map(_cleaned, text.splitlines()) if _is_complaint(line)]
    return _normalized(complaints[-1]) if complaints else None


def _cleaned(line: str) -> str:
    return _EVAL_PREFIX.sub("", line.strip())


def _is_complaint(line: str) -> bool:
    if not line or line.startswith("Exit code"):
        return False
    start = _TOOL_PREFIX.sub("", line, count=1)
    return bool(
        _COMPLAINT_START.match(line)
        or _COMPLAINT_START.match(start)
        or _COMPLAINT_ANYWHERE.search(line)
    )


def _normalized(line: str) -> str:
    line = _URL.sub("<url>", line)
    line = _QUOTED.sub("<x>", line)
    line = _PATH.sub("<path>", line)
    line = _HASH.sub("<hash>", line)
    line = _DURATION.sub("<n>", line)
    line = _NUMBER.sub("<n>", line)
    return cut_whole(" ".join(line.split()), MESSAGE_CHARS)


def cut_whole(text: str, limit: int) -> str:
    """Cut to `limit` characters without leaving half a placeholder (`<ur`) at the end."""
    return _PARTIAL_PLACEHOLDER.sub("", text[:limit]).rstrip()
