"""The lines of a failed command's output that say what broke, kept on the lesson.

The lesson quote keeps the end of the output, usually a pass/fail footer, so the failing tests and
the expected-versus-actual lines (`failure_excerpt.py`) are kept apart. Pure: text in, at most
MAX_LINES short lines out.
"""

import re

from symbiont.miner.failure_excerpt import assertion_excerpt

MAX_LINES = 6
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
    last = list(assertion_excerpt(text)) or _last_message_line(text)
    compiler = [m.strip() for m in _COMPILER_ERROR.findall(text)][-1:]
    ordered = dict.fromkeys(_trim(_NUMBER.sub("", line)) for line in (*found, *last, *compiler))
    return tuple(ordered)[:MAX_LINES]


def _last_message_line(text: str) -> list[str]:
    """The last assertion line, else the last exception line; [] when neither is printed."""
    asserted = [m.strip() for m in _ASSERTION.findall(text)][-1:]
    return asserted or [m.strip() for m in _EXCEPTION.findall(text)][-1:]


def _trim(line: str) -> str:
    """One line, whitespace collapsed, cut to LINE_CHARS."""
    flat = " ".join(line.split())
    return flat if len(flat) <= LINE_CHARS else flat[: LINE_CHARS - 3] + "..."
