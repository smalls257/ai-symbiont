"""What a rule says and when: house rules, rules for the work, and rules pinned to a file.

Each rule is said once per trigger, and the session remembers what it already said.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from symbiont.core.house_rules import Supersession, standing_corrections, standing_sentence
from symbiont.core.repeat import RepeatNote
from symbiont.core.rule_relevance import (
    MAX_RULE_NOTES,
    Rule,
    RuleMatch,
    file_scoped_rules,
    rule_sentence,
)
from symbiont.miner.painpoint import Signature
from symbiont.records.schema import Kind, Record

# Not a lesson id: the once-per-session key of the house-rules note.
STANDING_KEY = "house-rules"
# Not a prompt or failure: the once-per-session trigger of a rule whose file the agent touched.
FILE_TRIGGER = "file"


@dataclass(frozen=True)
class Occasion:
    """Why a rule may speak now: session, repository and trigger (prompt, failure or file)."""

    session_id: str
    project: str
    trigger: str


class RuleVoice:
    """Builds rule notes and remembers which were said; `silenced` is the developer's mute list."""

    def __init__(self, silenced: Callable[[str, Signature | None], bool]) -> None:
        """Start with nothing said."""
        self._silenced = silenced
        self._said: set[tuple[str, str, str]] = set()

    def standing(
        self, session_id: str, record: Record, rules: Sequence[Rule], leave_out: frozenset[str]
    ) -> list[RepeatNote]:
        """The house rules as one note, at the first prompt of a session only."""
        key = (session_id, STANDING_KEY, "prompt")
        if record.kind is not Kind.USER_TURN or key in self._said:
            return []
        corrections = standing_corrections(rules, leave_out)
        if not corrections:
            return []
        self._said.add(key)
        named = ", ".join(rule.ident for rule in corrections)
        return [RepeatNote(standing_sentence(corrections), None, f"rule: house rules ({named})")]

    def fresh(self, when: Occasion, live: Sequence[RuleMatch], room: int) -> list[RepeatNote]:
        """Up to `room` relevant rules not yet said for this trigger."""
        notes: list[RepeatNote] = []
        for match in live:
            key = (when.session_id, match.rule.ident, when.trigger)
            if len(notes) == room:
                break
            if key in self._said or self._muted(when.project, match.rule):
                continue
            self._said.add(key)
            notes.append(
                RepeatNote(rule_sentence(match.rule.words), match.rule.lesson, "rule: " + match.why)
            )
        return notes

    def on_file(
        self,
        session_id: str,
        record: Record,
        rules: Sequence[Rule],
        retired: dict[str, Supersession],
    ) -> tuple[list[RepeatNote], tuple[Supersession, ...]]:
        """Notes, and the rules put aside, for the file a read or edit touched; once per session.

        Reading is the point: the note arrives before the agent writes. Words and areas are not
        compared here, so only a rule the writer pinned to this file speaks.
        """
        found = file_scoped_rules(record.files, rules)
        live = [m for m in found if m.rule.ident not in retired]
        fresh = [m for m in live if not self._said_in_session(session_id, m.rule.ident)]
        notes = self.fresh(
            Occasion(session_id, record.project, FILE_TRIGGER), fresh, MAX_RULE_NOTES
        )
        gone = tuple(retired[m.rule.ident] for m in found if m.rule.ident in retired)
        return notes, gone

    def _said_in_session(self, session_id: str, ident: str) -> bool:
        """Whether this rule was already said in the session, for a prompt, failure or file."""
        return any(said[:2] == (session_id, ident) for said in self._said)

    def _muted(self, project: str, rule: Rule) -> bool:
        """Whether the developer silenced the kind of trouble behind a mined rule."""
        return rule.lesson is not None and self._silenced(project, rule.lesson.pain_point.signature)
