"""The expected-versus-actual lines of a failed test run, the evidence a lesson must keep.

Pure: runner output in, at most EXCERPT_CHARS characters of whole lines out, scrubbed where cut.
Runners: pytest (`E   - / +`), jest and vitest (`Expected:`/`Received:`), cargo (`left:`/`right:`),
go (`got`/`want`). A runner it does not know yields nothing; it never guesses.
"""

import re

from symbiont.miner.credential_scrub import scrub

# About three short lines: enough for an exception name and an expected/actual pair, short enough
# that a lesson stays a citation (same spirit as lessons.QUOTE_CHARS).
EXCERPT_CHARS = 300
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PYTEST_LINE = re.compile(r"^E(?:\s+(.*))?$")
_PYTEST_DIFF = re.compile(r"^[-+] ")
_EXCEPTION_HEAD = re.compile(r"^(?:[\w.]+\.)?(\w*(?:Error|Exception|Failure))\b")
_JEST_PAIR = re.compile(r"^\s*(?:Expected|Received)\b[^:\n]*:.*$", re.MULTILINE)
_JEST_HEADER = re.compile(r"^\s*expect\(.*\)\.\S+\(.*\)\s*$", re.MULTILINE)
_CARGO_HEADER = re.compile(r"^\s*assertion `left .*` failed.*$", re.MULTILINE)
_CARGO_SIDE = re.compile(r"^\s*(?:left|right):.*$", re.MULTILINE)
_GO_FAIL = re.compile(r"^--- FAIL: \S+.*$", re.MULTILINE)
_GO_DETAIL = re.compile(
    r"^\s+(?:\S+\.go:\d+:.*\b(?:got|want|expected|actual)\b.*|(?:expected|actual|want|got)\b.*)$",
    re.MULTILINE | re.IGNORECASE,
)


def assertion_excerpt(output: str) -> tuple[str, ...]:
    """Whole lines saying what was expected and what came out; () when the runner is unknown."""
    text = _ANSI.sub("", output)
    for extract in (_pytest, _jest, _cargo, _go):
        lines = extract(text)
        if lines:
            return _within_cap(lines)
    return ()


def one_line(excerpt: tuple[str, ...]) -> str:
    """The excerpt on one line, for a sentence that cannot hold a block."""
    return " / ".join(excerpt)


def _pytest(text: str) -> list[str]:
    """The first run of `E` lines, hint lines (`E   ? ++`) dropped, diff lines favored."""
    lines = [line for line in _first_pytest_group(text) if not line.startswith("? ")]
    diff = [line for line in lines if _PYTEST_DIFF.match(line)]
    return [*_exception_name(lines), *diff] if diff else lines


def _first_pytest_group(text: str) -> list[str]:
    """The text of the first block of consecutive `E` lines; [] when there is none."""
    group: list[str] = []
    for raw in text.splitlines():
        found = _PYTEST_LINE.match(raw)
        if found is None and group:
            break
        if found is not None and found.group(1):
            group.append(found.group(1).strip())
    return group


def _exception_name(lines: list[str]) -> list[str]:
    """The exception class of a group's first line, alone: its message repeats the diff."""
    head = _EXCEPTION_HEAD.match(lines[0]) if lines else None
    return [head.group(1)] if head else []


def _jest(text: str) -> list[str]:
    pairs = [line.strip() for line in _JEST_PAIR.findall(text)][:2]
    if len(pairs) < 2:
        return []
    return [*[line.strip() for line in _JEST_HEADER.findall(text)][:1], *pairs]


def _cargo(text: str) -> list[str]:
    sides = [line.strip() for line in _CARGO_SIDE.findall(text)][:2]
    if len(sides) < 2:
        return []
    return [*[line.strip() for line in _CARGO_HEADER.findall(text)][:1], *sides]


def _go(text: str) -> list[str]:
    names = [line.strip() for line in _GO_FAIL.findall(text)][:1]
    details = [line.strip() for line in _GO_DETAIL.findall(text)][:2]
    return [*names, *details] if details else []


def _within_cap(lines: list[str]) -> tuple[str, ...]:
    """Whole lines while they fit EXCERPT_CHARS; a first line that alone is too long is cut."""
    flat = [scrub(" ".join(item.split())) for item in lines]
    flat = [line for line in flat if line]
    kept: list[str] = []
    used = 0
    for line in flat:
        cost = len(line) + (1 if kept else 0)
        if used + cost > EXCERPT_CHARS:
            break
        kept.append(line)
        used += cost
    if kept or not flat:
        return tuple(kept)
    return (flat[0][: EXCERPT_CHARS - 3] + "...",)
