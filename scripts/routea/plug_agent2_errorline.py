"""PLUG-AGENT-2 error-line rule: the normalized error line is the key of a mistake.

Two runs make "the same mistake" when their error lines are equal after the volatile parts
(paths, line numbers, temp names, addresses, timestamps, long numbers) are masked. The class rule
splits generic environment errors from code-specific ones before any branch runs. Pure.
"""

import re

MAX_LENGTH = 200  # after masking; the same cut on both sides of a comparison
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?Z?")
UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
HEX_ADDRESS = re.compile(r"\b0x[0-9a-fA-F]{4,}\b")
TEMP_NAME = re.compile(r"\b(?:tmp|temp)[A-Za-z0-9_]{5,}\b")
PATH = re.compile(r"(?<![\w.])(?:[A-Za-z]:)?(?:\.{0,2}/)?(?:[\w.+@~-]+/)+[\w.+@-]*")
LINE_NUMBER = re.compile(r"\b(line|lineno|column|col)\s*[:=]?\s*\d+", re.IGNORECASE)
LONG_NUMBER = re.compile(r"\b\d{5,}\b")
SPACES = re.compile(r"\s+")

GENERIC_ENVIRONMENT = re.compile(
    r"^(?:ModuleNotFoundError|ImportError)\b"
    r"|command not found|not found in PATH|externally-managed-environment"
    r"|Could not find a version that satisfies|No matching distribution"
    r"|Permission denied|Network is unreachable|Connection refused|Temporary failure in name"
    r"|CERTIFICATE_VERIFY_FAILED|No space left on device"
    r"|No such file or directory: '(?:pip|pip3|python|python3|pytest|git|make|cmake|gcc|npm|node)'"
)


def normalize_error_line(line: str) -> str:
    """The error line with volatile parts masked; empty when nothing meaningful is left."""
    masked = ANSI.sub("", line)
    for pattern, mask in (
        (TIMESTAMP, "<time>"),
        (UUID, "<id>"),
        (HEX_ADDRESS, "<hex>"),
        (TEMP_NAME, "<tmp>"),
        (PATH, "<path>"),
        (LINE_NUMBER, r"\1 <n>"),
        (LONG_NUMBER, "<num>"),
    ):
        masked = pattern.sub(mask, masked)
    masked = SPACES.sub(" ", masked).strip()[:MAX_LENGTH]
    return (
        ""
        if not re.search(r"[A-Za-z]", SPACES.sub("", re.sub(r"<[a-z]+>", "", masked)))
        else masked
    )


def is_generic_environment(normalized_line: str) -> bool:
    """The pre-registered split: an environment or tooling error rather than a code-specific one."""
    return GENERIC_ENVIRONMENT.search(normalized_line) is not None
