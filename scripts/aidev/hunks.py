"""Unified-diff hunks as line positions, and tracking a hunk's lines through later commits.

A review comment and a later commit agree on a line only by its number in the file at a given
commit, so a hunk's added lines are carried forward commit by commit: shifted when a later change
sits elsewhere, "touched" when a later change removes one of them or inserts inside their span. A
patch that cannot be read raises `PatchError` instead of reading as "nothing changed". Pure: text
in, positions out.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_DEF = re.compile(r"\b(?:async\s+def|def|class)\s+([A-Za-z_]\w*)")
MAX_SECTION_NAME = 60  # a function name longer than this is not a name a lesson can show

Interval = tuple[int, int]  # first and last line, inclusive


class PatchError(ValueError):
    """A patch whose hunk header or body does not parse; names the reason."""


@dataclass(frozen=True)
class Hunk:
    """One `@@` block: added lines (new side), removed lines and insertion points (old side)."""

    added: tuple[int, ...]
    removed: tuple[int, ...]
    inserted_before: tuple[int, ...]  # one old-side line number per added line
    section: str  # git's function context after the header, may be empty

    def added_intervals(self) -> tuple[Interval, ...]:
        """The added lines as runs of consecutive line numbers."""
        return _runs(self.added)


@dataclass(frozen=True)
class FileChange:
    """Every hunk one commit made to one file, merged for lookup."""

    removed: tuple[int, ...]
    inserted_before: tuple[int, ...]

    @classmethod
    def of(cls, hunks: list[Hunk]) -> "FileChange":
        """Merge a file's hunks into sorted old-side positions."""
        removed = sorted(n for h in hunks for n in h.removed)
        inserted = sorted(n for h in hunks for n in h.inserted_before)
        return cls(tuple(removed), tuple(inserted))

    def touches(self, span: Interval) -> bool:
        """True if this change removes a line in the span or inserts strictly inside it."""
        first, last = span
        if bisect_right(self.removed, last) > bisect_left(self.removed, first):
            return True
        return bisect_right(self.inserted_before, last) > bisect_right(self.inserted_before, first)

    def shift(self, span: Interval) -> Interval:
        """Where an untouched span sits after this change."""
        offset = bisect_right(self.inserted_before, span[0]) - bisect_left(self.removed, span[0])
        return span[0] + offset, span[1] + offset


def parse_patch(patch: str) -> list[Hunk]:
    """Every hunk of one file's patch; raises PatchError on a body line outside any hunk."""
    hunks: list[Hunk] = []
    lines = patch.splitlines()
    index = 0
    while index < len(lines):
        match = _HEADER.match(lines[index])
        if match is None:
            raise PatchError(f"line {index + 1} is not inside a hunk")
        hunk, index = _read_hunk(match, lines, index + 1)
        hunks.append(hunk)
    return hunks


def _read_hunk(match: re.Match[str], lines: list[str], index: int) -> tuple[Hunk, int]:
    old, new = int(match.group(1)), int(match.group(3))
    added: list[int] = []
    removed: list[int] = []
    inserted: list[int] = []
    while index < len(lines) and not lines[index].startswith("@@"):
        mark = lines[index][:1]
        if mark == "+":
            added.append(new)
            inserted.append(old)
            new += 1
        elif mark == "-":
            removed.append(old)
            old += 1
        elif mark != "\\":
            old, new = old + 1, new + 1
        index += 1
    hunk = Hunk(tuple(added), tuple(removed), tuple(inserted), match.group(5))
    return hunk, index


def anchor_line(diff_hunk: str) -> int | None:
    """The new-side line a review comment sits on: the last line of its `diff_hunk`.

    None when the comment sits on a removed line (the old side), which no added line owns.
    Raises PatchError when the hunk has no header.
    """
    lines = diff_hunk.splitlines()
    match = _HEADER.match(lines[0]) if lines else None
    if match is None:
        raise PatchError("review hunk has no header")
    new = int(match.group(3)) - 1
    last_mark = " "
    for line in lines[1:]:
        last_mark = line[:1]
        if last_mark in ("+", " ", ""):
            new += 1
    return None if last_mark == "-" else new


def section_name(section: str) -> str | None:
    """The function or class named in git's hunk context, if it names one briefly."""
    match = _DEF.search(section)
    if match is None or len(match.group(1)) > MAX_SECTION_NAME:
        return None
    return match.group(1)


def _runs(numbers: tuple[int, ...]) -> tuple[Interval, ...]:
    runs: list[Interval] = []
    for number in numbers:
        if runs and runs[-1][1] == number - 1:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    return tuple(runs)
