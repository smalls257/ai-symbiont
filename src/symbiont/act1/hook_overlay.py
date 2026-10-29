"""What the demo clip's side panel says about one played move (pure: no pixels, no engine).

Violation prevented: Paper Tiger in the hook. An overlay that names a pain point the tagger did
not fire would make the opening a lie, so a card can only be built from a `MoveRun` and the
`GamePain`s that `tag_pains` returned for it; there is no way to hand it a free-text label. A
pain the label table lacks raises `KeyError`, never a raw enum value (Silent Fallback).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.act1.game_pains import GamePain
from symbiont.act1.steplog import MoveRun

PAIN_LABELS = {
    GamePain.WALL_BUMP: "wall bump",
    GamePain.ROOM_REENTERED: "room re-entered",
    GamePain.ROOM_RECHECKED: "room re-checked",
    GamePain.WASTED_MOVE: "wasted move",
}
# About 0.8 s at 30 frames per second: long enough to read two words, short enough not to hide play.
BANNER_FRAMES = 24


@dataclass(frozen=True)
class PlayerStats:
    """The game's own counters after a move, as ViZDoom reports them; the panel computes none."""

    health: int
    armor: int
    ammo: int
    kills: int
    damage_dealt: int
    damage_taken: int
    items: int
    secrets: int
    dead: bool


@dataclass(frozen=True)
class MoveCard:
    """The panel text for one move: its step, the scripted move chosen, how it ended, its pains."""

    step: int
    move: str
    outcome: str
    pains: tuple[str, ...]
    stats: PlayerStats | None = None  # None for a clip that does not read game variables


def card_for(
    step: int, run: MoveRun, pains: Sequence[GamePain], stats: PlayerStats | None = None
) -> MoveCard:
    """Panel text from the played move and the tagger's verdict. Raises KeyError for a new pain."""
    return MoveCard(step, run.label, run.outcome, tuple(PAIN_LABELS[pain] for pain in pains), stats)


def banner_start(frame_count: int) -> int:
    """Index of the first frame of a move that shows its pain banner (the last BANNER_FRAMES)."""
    return max(0, frame_count - BANNER_FRAMES)


def tally(cards: Sequence[MoveCard]) -> Counter[str]:
    """How often each pain label fired across the cards so far."""
    return Counter(label for card in cards for label in card.pains)
