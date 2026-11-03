"""What `symbiont why` says about lessons put aside for a later correction of the developer's."""

import json
from pathlib import Path

SHOWN = 3


def superseded_sentences(runs_dir: Path, project: str) -> list[str]:
    """Up to SHOWN sentences, newest first, one per lesson set aside in `project`.

    A line of an event log that is not JSON raises ValueError naming the file.
    """
    seen: dict[str, str] = {}
    for events in sorted(runs_dir.glob("*/events.jsonl"), reverse=True):
        for line in reversed(events.read_text(encoding="utf-8").splitlines()):
            entries = _entries(events, line, project)
            for entry in entries:
                seen.setdefault(entry["lesson"], _sentence(entry))
    return list(seen.values())[:SHOWN]


def _entries(events: Path, line: str, project: str) -> list[dict[str, str]]:
    """The supersession entries of one log line for `project`, none for other events."""
    try:
        event = json.loads(line)
    except ValueError as exc:
        raise ValueError(f"{events} holds a line that is not JSON: {exc}") from exc
    if not isinstance(event, dict) or event.get("project") != project:
        return []
    found = event.get("superseded")
    return found if isinstance(found, list) else []


def _sentence(entry: dict[str, str]) -> str:
    """One entry as prose: the lesson that stayed quiet and the correction that outranks it."""
    return (
        f'Held back as out of date: "{entry["lesson_excerpt"]}" '
        f'You corrected it later: "{entry["by_excerpt"]}"'
    )
