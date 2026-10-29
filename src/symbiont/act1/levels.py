"""Which Freedoom levels meta-training may see, and which are held out for scoring (pure).

Every fourth map in play order is held out (prereg 2026-10-27-act1-level-split.md for freedoom2.wad
MAP01 to MAP32, 2026-10-29-phase1-level-split.md for freedoom1.wad E1M1 to E4M9); MAP01 trains. A
level outside both WADs raises `UnknownLevelError`, and `require_training` names a held-out level
in its error so a collector cannot write one into a scored store.
"""

import re
from enum import StrEnum

WAD_PROJECT = "freedoom2"
MAP_COUNT = 32
HOLD_OUT_EVERY = 4
PHASE_ONE_EPISODES = 4
PHASE_ONE_MAPS_PER_EPISODE = 9


class LevelSplit(StrEnum):
    """Which side of the split a level is on."""

    TRAINING = "training"
    HELD_OUT = "held_out"


class Project(StrEnum):
    """Which Freedoom WAD a level name belongs to."""

    FREEDOOM2 = "freedoom2"
    FREEDOOM1 = "freedoom1"


class UnknownLevelError(ValueError):
    """A level name that is none of freedoom2.wad's MAP01..MAP32 or freedoom1.wad's E1M1..E4M9."""


class HeldOutLevelError(ValueError):
    """A held-out level was offered to meta-training."""


def _map_number(level: str) -> int:
    """The play-order position of a level (MAPxx, or ExMy in Phase 1); else UnknownLevelError."""
    if level.startswith("MAP") and level[3:].isdigit() and len(level) == 5:
        number = int(level[3:])
        if not 1 <= number <= MAP_COUNT:
            raise UnknownLevelError(f"{level!r} is outside MAP01..MAP{MAP_COUNT:02d}")
        return number
    return _phase_one_position(level)


def _phase_one_position(level: str) -> int:
    """The 1-based play-order position of an ExMy level: (episode - 1) * 9 + map."""
    found = re.fullmatch(r"E(\d)M(\d)", level)
    if found is None:
        raise UnknownLevelError(f"{level!r} is not a level name like MAP07 or E2M3")
    episode, number = int(found[1]), int(found[2])
    if not (1 <= episode <= PHASE_ONE_EPISODES and 1 <= number <= PHASE_ONE_MAPS_PER_EPISODE):
        raise UnknownLevelError(f"{level!r} is outside E1M1..E4M9")
    return (episode - 1) * PHASE_ONE_MAPS_PER_EPISODE + number


def project_of(level: str) -> Project:
    """The WAD a level name belongs to. Raises UnknownLevelError."""
    _map_number(level)
    return Project.FREEDOOM2 if level.startswith("MAP") else Project.FREEDOOM1


def split_of(level: str) -> LevelSplit:
    """The level's side of the split. Raises UnknownLevelError."""
    if _map_number(level) % HOLD_OUT_EVERY == 0:
        return LevelSplit.HELD_OUT
    return LevelSplit.TRAINING


def level_names(project: Project) -> tuple[str, ...]:
    """Every level of one WAD in play order."""
    if project == Project.FREEDOOM2:
        return tuple(f"MAP{n:02d}" for n in range(1, MAP_COUNT + 1))
    return tuple(
        f"E{e}M{m}"
        for e in range(1, PHASE_ONE_EPISODES + 1)
        for m in range(1, PHASE_ONE_MAPS_PER_EPISODE + 1)
    )


def levels_in(split: LevelSplit, project: Project = Project.FREEDOOM2) -> tuple[str, ...]:
    """Every level on one side of the split, in play order (Phase 2 unless the project says)."""
    return tuple(level for level in level_names(project) if split_of(level) == split)


def require_training(level: str) -> None:
    """Refuse a held-out level. Raises HeldOutLevelError, or UnknownLevelError for a bad name."""
    if split_of(level) == LevelSplit.HELD_OUT:
        raise HeldOutLevelError(
            f"{level} is held out for scoring and never enters meta-training "
            "(prereg/2026-10-27-act1-level-split.md)"
        )
