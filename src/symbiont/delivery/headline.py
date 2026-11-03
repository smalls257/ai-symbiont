"""The one-line headline a developer sees for a note.

Both harnesses show a hook's `systemMessage` as
one gray status line, cut at terminal width for a few seconds (measured in Muse Code), so a
full note arrives cut mid-word and says nothing. The model still gets the full note through
`additionalContext`; this module only words what the developer reads. It carries no learning
and no matching: it shortens the sentence it is given and names where it came from.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# A status line is one gray line truncated at terminal width; 90 fits an 80-column terminal
# plus slack for the harness's own gutter (measured in Muse Code's interactive TUI).
MAX_HEADLINE_CHARS = 90
_PREFIX = "symbiont · "
_ELLIPSIS = "…"
_NOTE_TAGS = ("[symbiont]", "In this repo:", "Last time,")
_CLAUSE_END = re.compile(r"[.;:!?](?:\s|$)")


def headline(notes: Sequence[str]) -> str:
    """The developer-facing line for these notes; empty when there are none."""
    if not notes:
        return ""
    if len(notes) == 1:
        return _single(notes[0])
    return _several(notes)


def _single(note: str) -> str:
    where = f" ({_provenance(note)})"
    room = MAX_HEADLINE_CHARS - len(_PREFIX) - len(where)
    return f"{_PREFIX}{_shortened(_lead_clause(note), room)}{where}"


def _several(notes: Sequence[str]) -> str:
    head = f"{_PREFIX}{len(notes)} notes: "
    tail = f" +{len(notes) - 1}"
    room = MAX_HEADLINE_CHARS - len(head) - len(tail)
    return f"{head}{_shortened(_lead_clause(notes[0]), room)}{tail}"


def _provenance(note: str) -> str:
    """Where the lesson came from, read off the sentence the service wrote."""
    if "corrected" in note.lower():
        return "your correction"
    if note.lstrip().startswith("Last time"):
        return "your history"
    return "this repo's rule"


def _lead_clause(note: str) -> str:
    """The first clause of the lesson, without the note's own tags."""
    text = note.strip()
    for tag in _NOTE_TAGS:
        text = text.removeprefix(tag).strip()
    if "corrected" in text.lower() and " on: " in text:
        text = text.split(" on: ", 1)[1]
    ended = _CLAUSE_END.search(text)
    clause = text[: ended.start()] if ended else text
    return " ".join(clause.split())


def _shortened(clause: str, room: int) -> str:
    """The clause cut at the last whole word that fits `room` with an ellipsis."""
    if len(clause) <= room:
        return clause
    kept = room - len(_ELLIPSIS)
    if not clause[kept].isspace():
        kept = clause.rfind(" ", 0, kept)
    return clause[: max(kept, 0)].rstrip(" ,;:-") + _ELLIPSIS
