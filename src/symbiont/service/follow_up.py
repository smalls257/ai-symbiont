"""Follows each shown Plug note for its next actions and logs what the agent did with it."""

from dataclasses import dataclass, field

from symbiont.core.note_outcome import ACTIONS_WATCHED, classify_action
from symbiont.records.schema import Kind, Record
from symbiont.service.events import Call, EventLog

ACTION_KINDS = frozenset({Kind.COMMAND, Kind.READ, Kind.EDIT})


@dataclass(frozen=True)
class ShownNote:
    """A note that was shown: its lesson id, the rule that let it through, the fixes it names."""

    note_id: str
    rule: str
    fixes: tuple[str, ...]


@dataclass
class _Watch:
    note: ShownNote
    seen: list[str] = field(default_factory=list)


class FollowUp:
    """One open watch per project; a newer note replaces an unfinished one (logged as it stood)."""

    def __init__(self, events: EventLog) -> None:
        self._events = events
        self._open: dict[str, _Watch] = {}

    def shown(self, call: Call, project: str, note: ShownNote) -> None:
        """Log the note and start watching the project's next actions."""
        self._events.append_note_shown(call, note.note_id, note.rule)
        previous = self._open.get(project)
        if previous is not None:
            self._finish(call, previous)
        self._open[project] = _Watch(note)

    def observed(self, call: Call, project: str, record: Record) -> None:
        """Classify an action record against the open watch; log after ACTIONS_WATCHED."""
        watch = self._open.get(project)
        if watch is None or record.kind not in ACTION_KINDS:
            return
        watch.seen.append(classify_action(watch.note.fixes, record.command, record.exit_code).value)
        if len(watch.seen) >= ACTIONS_WATCHED:
            del self._open[project]
            self._finish(call, watch)

    def _finish(self, call: Call, watch: _Watch) -> None:
        self._events.append_note_outcome(call, watch.note.note_id, watch.note.rule, watch.seen)
