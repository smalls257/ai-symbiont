"""Which Freedoom levels meta-training may see, and which are held out for scoring (pure).

The split is fixed by rule before any episode is logged (prereg/2026-10-27-act1-level-split.md):
every fourth map of freedoom2.wad is held out, so held-out levels spread across the whole game
rather than bunching at the hard end. MAP01 stays in training because development runs played it.

Violation prevented: Silent Fallback at the hold-out boundary. A level outside the 32 maps raises
`UnknownLevelError` instead of landing in either split by default, and
`require_training` names a held-out level in its error so a collector cannot write one into a
store a scored run reads.
"""

from enum import StrEnum

WAD_PROJECT = "freedoom2"
MAP_COUNT = 32
HOLD_OUT_EVERY = 4


class LevelSplit(StrEnum):
    """Which side of the split a level is on."""

    TRAINING = "training"
    HELD_OUT = "held_out"


class UnknownLevelError(ValueError):
    """A level name that is not one of freedoom2.wad's MAP01..MAP32."""


class HeldOutLevelError(ValueError):
    """A held-out level was offered to meta-training."""


def _map_number(level: str) -> int:
    if not (level.startswith("MAP") and level[3:].isdigit() and len(level) == 5):
        raise UnknownLevelError(f"{level!r} is not a level name like MAP07")
    number = int(level[3:])
    if not 1 <= number <= MAP_COUNT:
        raise UnknownLevelError(f"{level!r} is outside MAP01..MAP{MAP_COUNT:02d}")
    return number


def split_of(level: str) -> LevelSplit:
    """The level's side of the split. Raises UnknownLevelError."""
    if _map_number(level) % HOLD_OUT_EVERY == 0:
        return LevelSplit.HELD_OUT
    return LevelSplit.TRAINING


def levels_in(split: LevelSplit) -> tuple[str, ...]:
    """Every level on one side of the split, in map order."""
    every = (f"MAP{n:02d}" for n in range(1, MAP_COUNT + 1))
    return tuple(level for level in every if split_of(level) == split)


def require_training(level: str) -> None:
    """Refuse a held-out level. Raises HeldOutLevelError, or UnknownLevelError for a bad name."""
    if split_of(level) == LevelSplit.HELD_OUT:
        raise HeldOutLevelError(
            f"{level} is held out for scoring and never enters meta-training "
            "(prereg/2026-10-27-act1-level-split.md)"
        )
