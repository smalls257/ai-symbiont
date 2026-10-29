"""One played scripted move, as the episode loop reports it (pure data, no clock, no store).

Prevents Leaky Narrative: consumers of the move stream (the episode log) get a typed kind and the
two views around the move, so they never re-parse `"label -> outcome"` history strings or reach
into the engine. An unknown move class raises `TypeError`, never a default kind (Silent Fallback).
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
