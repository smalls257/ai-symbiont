"""The lines of a failed command's output that say what broke, kept on the lesson.

The lesson's quote is clipped to its last few hundred characters, which for a test run is usually
the "1 failed in 0.4s" footer; a reader (or the session's model) judging the lesson needs the
failing test and the assertion. Pure: text in, at most MAX_LINES short lines out.
"""

import re

MAX_LINES = 4
LINE_CHARS = 160
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR)\s+\S+::\S+.*$", re.MULTILINE)
_ASSERTION = re.compile(r"^E\s+(\S.*)$", re.MULTILINE)
_EXCEPTION = re.compile(r"^\s*(?:[\w.]+\.)?\w*(?:Error|Exception|Failure)\b.*$", re.MULTILINE)
_COMPILER_ERROR = re.compile(r"^\S.*\berror\s+TS\d+:.*$", re.MULTILINE)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_NUMBER = re.compile(r"\b\d+\.\d+s\b")


def key_error_lines(output: str) -> tuple[str, ...]:
    """The failing tests, then the last assertion or exception line, trimmed; () when none."""
    text = _ANSI.sub("", output)
    found = [m.strip() for m in _FAILED_TEST.findall(text)][-2:]
    last = [m.strip() for m in _ASSERTION.findall(text)][-1:]
    if not last:
        last = [m.strip() for m in _EXCEPTION.findall(text)][-1:]
    compiler = [m.strip() for m in _COMPILER_ERROR.findall(text)][-1:]
    ordered = dict.fromkeys(_trim(_NUMBER.sub("", line)) for line in (*found, *last, *compiler))
    return tuple(ordered)[:MAX_LINES]


def _trim(line: str) -> str:
    """One line, whitespace collapsed, cut to LINE_CHARS."""
    flat = " ".join(line.split())
    return flat if len(flat) <= LINE_CHARS else flat[: LINE_CHARS - 3] + "..."
