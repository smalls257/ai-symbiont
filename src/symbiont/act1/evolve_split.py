"""The three-way level split and every draw of cases, reproducible from the run seed (pure).

Held-out levels come from the frozen level-split prereg (every fourth map); validation levels are
every sixth training map and never feed selection or picking; selection draws from the rest. A
level that fails its smoke test is dropped and listed with the reason, never filled in. Draws are
functions of (run seed, generation), so any generation can be replayed and audited.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.act1.game_fitness import Case
from symbiont.act1.levels import LevelSplit, levels_in, require_training
from symbiont.act1.move_cuts import HARDER_SKILL, NORMAL_SKILL, CutSetting

# Validation is spread over the maps that pass the smoke test (a sixth of them, at least three):
# with all 24 training maps passing that is 4, with the 10 that pass now it is 3.
VALIDATION_FLOOR = 3
LEVELS_PER_GENERATION = 4  # design section 4
TRAINING_SKILLS = (2, 3, 4)  # design section 5.2
# Plan ruling 2: skill 4 plus cuts is the final test's harder condition, so training never has it.
CUTS_OFF_AT_SKILL = HARDER_SKILL
FINAL_SEEDS = (1001, 1002)  # design section 6, fixed in the prereg
# Training and validation seeds live far from the final test's and from the cross-level check's
# (3000 to 3999); each generation owns a block of 1000.
GENERATION_SEED_BASE = 10_000
VALIDATION_SEED_BASE = 500_000
SEED_BLOCK = 1_000


class Condition(StrEnum):
    """The two conditions of the final test."""

    NORMAL = "normal"
    HARDER = "harder"


class MissingSmokeResultError(ValueError):
    """A level has no smoke-test result; a pass is never assumed."""


class NotEnoughLevelsForExplorationError(ValueError):
    """Fewer levels than a generation draws were given to the exploratory split."""


class NotSelectionLevelError(ValueError):
    """A validation, held-out or dropped level was offered to selection."""


@dataclass(frozen=True)
class SmokeResult:
    """The smoke test's verdict on one level; `reason` says why a level was dropped."""

    passed: bool
    reason: str


@dataclass(frozen=True)
class EvolveSplit:
    """Which levels play which role. `dropped` maps a failed level to its reason."""

    held_out: tuple[str, ...]
    validation: tuple[str, ...]
    selection: tuple[str, ...]
    dropped: Mapping[str, str]

    @classmethod
    def of(cls, smoke: Mapping[str, SmokeResult]) -> "EvolveSplit":
        """Split by rule from the smoke results; raises MissingSmokeResultError."""
        every = levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT)
        missing = [level for level in every if level not in smoke]
        if missing:
            raise MissingSmokeResultError(f"no smoke result for {', '.join(missing)}")
        dropped = {m: smoke[m].reason for m in sorted(every) if not smoke[m].passed}
        passing = [m for m in levels_in(LevelSplit.TRAINING) if m not in dropped]
        validation = _validation_levels(passing)
        selection = tuple(m for m in passing if m not in validation)
        held_out = tuple(m for m in levels_in(LevelSplit.HELD_OUT) if m not in dropped)
        return cls(held_out, validation, selection, dropped)

    @classmethod
    def exploratory(cls, levels: Sequence[str]) -> "EvolveSplit":
        """Stand-in split for too few navigable levels: one pool, validation told apart by seeds.

        Weaker than validation levels (a card can still learn these maps), so runs on it are
        exploratory; there is no held-out list.
        """
        for level in levels:
            require_training(level)
        if len(levels) < LEVELS_PER_GENERATION:
            raise NotEnoughLevelsForExplorationError(
                f"{len(levels)} level(s); a generation draws {LEVELS_PER_GENERATION}"
            )
        return cls((), tuple(levels), tuple(levels), {})

    def require_selection(self, level: str) -> None:
        """Raises NotSelectionLevelError unless the level may feed selection."""
        if level not in self.selection:
            raise NotSelectionLevelError(f"{level} is not a selection level of this run")


def _validation_levels(passing: list[str]) -> tuple[str, ...]:
    """Validation maps spread evenly over the passing training maps in map order.

    The count is the larger of VALIDATION_FLOOR and a sixth of the passing maps; each is the map
    in the middle of one of that many equal parts of the list.
    """
    count = max(VALIDATION_FLOOR, len(passing) // 6)
    if len(passing) - count < LEVELS_PER_GENERATION:
        raise NotEnoughLevelsForExplorationError(
            f"{len(passing)} passing training maps leave fewer than {LEVELS_PER_GENERATION} "
            f"for selection after {count} validation maps"
        )
    return tuple(passing[len(passing) * (2 * k + 1) // (2 * count)] for k in range(count))


def _draw(split: EvolveSplit, generation: int, run_seed: int) -> tuple[list[str], int, CutSetting]:
    """A generation's four levels, its one skill and its cut setting (plan ruling 2).

    Cuts are on at skills 2 and 3 and off at 4, so training never sees the harder condition.
    """
    rng = random.Random(f"{run_seed}:{generation}:cases")
    levels = rng.sample(split.selection, LEVELS_PER_GENERATION)
    skill = rng.choice(TRAINING_SKILLS)
    return levels, skill, CutSetting.NONE if skill == CUTS_OFF_AT_SKILL else CutSetting.TEN_PERCENT


def generation_cases(
    split: EvolveSplit, generation: int, run_seed: int, games_per_case: int
) -> tuple[Case, ...]:
    """Four selection levels, `games_per_case` fresh seeds each, one skill and cut setting."""
    levels, skill, cuts = _draw(split, generation, run_seed)
    block = GENERATION_SEED_BASE + generation * SEED_BLOCK
    return tuple(
        Case(level, block + repeat * LEVELS_PER_GENERATION + slot, skill, cuts)
        for repeat in range(games_per_case)
        for slot, level in enumerate(levels)
    )


def validation_cases(split: EvolveSplit, generation: int, run_seed: int) -> tuple[Case, ...]:
    """One case per validation level, under the same skill and cuts as the generation's training."""
    _, skill, cuts = _draw(split, generation, run_seed)
    block = VALIDATION_SEED_BASE + generation * SEED_BLOCK
    return tuple(
        Case(level, block + slot, skill, cuts) for slot, level in enumerate(split.validation)
    )


def final_cases(split: EvolveSplit) -> tuple[Case, ...]:
    """Every passing held-out level x both seeds x normal and harder conditions."""
    conditions = (
        (NORMAL_SKILL, CutSetting.NONE),
        (HARDER_SKILL, CutSetting.TEN_PERCENT),
    )
    return tuple(
        Case(level, seed, skill, cuts)
        for level in split.held_out
        for seed in FINAL_SEEDS
        for skill, cuts in conditions
    )


def condition_of(case: Case) -> Condition:
    """The final-test condition a case belongs to; raises ValueError for a training draw."""
    if (case.skill, case.cuts) == (NORMAL_SKILL, CutSetting.NONE):
        return Condition.NORMAL
    if (case.skill, case.cuts) == (HARDER_SKILL, CutSetting.TEN_PERCENT):
        return Condition.HARDER
    raise ValueError(f"skill {case.skill} with cuts {case.cuts} is not a final-test condition")
