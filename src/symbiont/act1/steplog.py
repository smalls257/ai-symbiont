"""One played scripted move and one model decision, as the episode loop reports them (pure data).

`Decision` lives here, not in episode.py, so decision-log readers stay pure. Consumers get a typed
kind and the two views around a move, never `"label -> outcome"` strings to re-parse or the
engine to reach into. An unknown move class raises `TypeError`, never a default kind.
"""

from dataclasses import dataclass
from enum import StrEnum

from symbiont.act1.env_text import GameStateView
from symbiont.act1.goto import GoTo
from symbiont.act1.moves import OpenDoor, RetreatTo, ShootNearest, Turn, WalkTo
from symbiont.act1.strategy import Move


class MoveKind(StrEnum):
    """Coarse move kinds; the episode log tags each record with one."""

    WALK = "walk"
    TURN = "turn"
    SHOOT = "shoot"
    USE = "use"


def kind_of(move: Move) -> MoveKind:
    """The coarse kind of a move; raises TypeError for a class the parser cannot produce."""
    if isinstance(move, WalkTo | RetreatTo | GoTo):
        return MoveKind.WALK
    if isinstance(move, Turn):
        return MoveKind.TURN
    if isinstance(move, ShootNearest):
        return MoveKind.SHOOT
    if isinstance(move, OpenDoor):
        return MoveKind.USE
    raise TypeError(f"not a scripted move: {type(move).__name__}")


@dataclass(frozen=True)
class MoveRun:
    """A move that started: `after` is None when the episode ended during it."""

    decision: int
    label: str
    kind: MoveKind
    outcome: str  # what execute_move returned, not the "label -> outcome" history string
    tics: int
    before: GameStateView
    after: GameStateView | None


@dataclass(frozen=True)
class Decision:
    """One model decision: what it saw, what it said, how the scripts fared."""

    index: int
    observation: str
    reply: str
    status: (
        str  # "ok", "invalid" (not a valid strategy) or "truncated" (cut off by the token limit)
    )
    rejected: str | None
    finish_reason: str
    reasoning_chars: int
    outcomes: tuple[str, ...]
    model_seconds: float
    # Server-counted tokens; None for scripted policies, which call no model.
    tokens_in: int | None = None
    tokens_out: int | None = None
