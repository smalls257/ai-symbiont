"""What a diff put in and took out, as comparable lines.

OpenHands records no position for an edit, and review hunks and commits use
different line numbering, so edits are compared by content: a line is the
same line if its text matches once indentation is ignored. Lines with no
letters or digits (`)`, `}`, blank) match everywhere and prove nothing, so
they are left out.
"""

import re

_MEANINGFUL = re.compile(r"[A-Za-z0-9]")


def added_lines(diff: str) -> frozenset[str]:
    """Meaningful lines the diff added, stripped of indentation."""
    return _lines_marked(diff, "+")


def removed_lines(diff: str) -> frozenset[str]:
    """Meaningful lines the diff removed, stripped of indentation."""
    return _lines_marked(diff, "-")


def _lines_marked(diff: str, marker: str) -> frozenset[str]:
    header = marker * 3
    found = set()
    for line in diff.splitlines():
        if not line.startswith(marker) or line.startswith(header):
            continue
        text = line[1:].strip()
        if _MEANINGFUL.search(text):
            found.add(text)
    return frozenset(found)
