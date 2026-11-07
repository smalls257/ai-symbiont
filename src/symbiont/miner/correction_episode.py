"""Where the agent first went wrong before a correction, and how many steps that cost.

Walks back from the developer's correction through the agent's actions since the previous
developer turn, so an episode never reaches past what that turn already settled.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.changes import applied_edit
from symbiont.miner.commands import program_words
from symbiont.miner.resolutions import is_action
from symbiont.records.schema import Kind, Record


@dataclass(frozen=True)
class Episode:
    """The action the correction is about, the actions it cost, and the agent's next edit."""

    first_wrong: Record | None
    cost_steps: int
    next_edit: Record | None


NO_EPISODE = Episode(None, 0, None)


def episode_of(turn: Record, records: Sequence[Record]) -> Episode:
    """The episode of the correction `turn` in its session's `records`."""
    ordered = sorted(records, key=lambda record: record.step)
    actions = [r for r in _stretch_before(turn, ordered) if is_action(r)]
    return Episode(
        first_wrong=_addressed(turn.raw, actions),
        cost_steps=_cost(turn.raw, actions),
        next_edit=_next_edit(turn, ordered),
    )


def _stretch_before(turn: Record, ordered: Sequence[Record]) -> list[Record]:
    """Records after the previous developer turn and before `turn`, in order."""
    stretch: list[Record] = []
    for record in reversed([r for r in ordered if r.step < turn.step]):
        if record.kind is Kind.USER_TURN:
            break
        stretch.append(record)
    return stretch[::-1]


def _addressed(text: str, actions: Sequence[Record]) -> Record | None:
    """The earliest action the text names, else the first failed one, else the first edit."""
    named = next((a for a in actions if _names(text, a)), None)
    failed = next(
        (a for a in actions if a.kind is Kind.COMMAND and a.exit_code not in (None, 0)), None
    )
    edited = next((a for a in actions if applied_edit(a)), None)
    return named or failed or edited


def _cost(text: str, actions: Sequence[Record]) -> int:
    """Actions from the addressed one through the last before the correction."""
    first = _addressed(text, actions)
    return 0 if first is None else len(actions) - actions.index(first)


def _next_edit(turn: Record, ordered: Sequence[Record]) -> Record | None:
    """The agent's first applied edit after the correction, before the developer speaks again."""
    for record in (r for r in ordered if r.step > turn.step):
        if record.kind is Kind.USER_TURN:
            return None
        if applied_edit(record):
            return record
    return None


def _names(text: str, action: Record) -> bool:
    """True when the text names the action's file or its program."""
    if action.kind is Kind.COMMAND:
        program = program_words(action.command or "")[0]
        return program != "-" and _mentions(text, program)
    return any(
        _mentions(text, path) or _mentions(text, path.rsplit("/", 1)[-1]) for path in action.files
    )


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(name)}(?!\w)", text) is not None
