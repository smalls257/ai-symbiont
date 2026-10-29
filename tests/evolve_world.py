"""A tiny world for dry-run tests: a hidden-rule fake player, seed cards, tools and a runner."""

import hashlib
import random

from symbiont.act1.card_genome import Card
from symbiont.act1.evolution import RunRules, evolve
from symbiont.act1.evolve_split import (
    SEED_BLOCK,
    VALIDATION_SEED_BASE,
    EvolveSplit,
    SmokeResult,
)
from symbiont.act1.game_fitness import GameResult, Grade
from symbiont.act1.generation import OperatorSchedule, VariationTools
from symbiont.act1.levels import LevelSplit, levels_in
from symbiont.act1.offline_author import OFFLINE_LESSONS, AllowAllJudge, OfflineAuthor
from symbiont.act1.run_guards import SpendRoom

EVERY_MAP = tuple(f"MAP{n:02d}" for n in range(1, 33))
SPLIT = EvolveSplit.of({m: SmokeResult(True, "") for m in EVERY_MAP})
PLENTY = SpendRoom(remaining_usd=10.0, doubling_cost_usd=1.0)
HELD_OUT = set(levels_in(LevelSplit.HELD_OUT))


def doors(card):
    """The hidden rule's input: lessons that talk about doors."""
    return sum("door" in f"{lesson.instead} {lesson.went_wrong}".lower() for lesson in card.lessons)


def wobble(card, case, scale):
    """Seeded noise in -scale..scale from the case alone: every card feels the same luck.

    Card-specific noise would leave the card means apart by chance, and a like-for-like check on
    cards with no true difference is then a coin flip; shared luck makes the test deterministic.
    """
    digest = hashlib.sha256(f"{case}".encode()).digest()
    return scale * (digest[0] / 127.5 - 1)


class FakePlayer:
    """Scores by a hidden rule: door lessons help, more on some levels. The rest are knobs."""

    def __init__(self, noise=0.01, ungraded_every=0, validation_drop=0.0, effect=0.06):
        self.noise, self.effect = noise, effect
        self.ungraded_every, self.validation_drop = ungraded_every, validation_drop
        self.calls, self.levels = 0, []

    def play(self, card, case):
        self.calls += 1
        self.levels.append(case.level)
        if self.ungraded_every and self.calls % self.ungraded_every == 0:
            return result(card, case, 0.0, Grade.UNGRADED)
        strength = 1 + (int(case.level[3:]) % 3) / 3  # doors help everywhere, more on some levels
        share = 0.5 + self.effect * doors(card) * strength + wobble(card, case, self.noise)
        if case.level in SPLIT.validation and self.validation_drop:
            generation = (case.seed - VALIDATION_SEED_BASE) // SEED_BLOCK
            share = 1.0 - self.validation_drop * generation
        return result(card, case, min(max(share, 0.0), 1.0), Grade.GRADED)


def result(card, case, share, grade):
    reason = None if grade == Grade.GRADED else "FakeError"
    return GameResult(case, card.card_id, grade, False, share, 0, False, 0, 0, reason)


def seeds():
    """Six seed cards; the first three (the noise-check cards) hold 0, 1 and 2 door lessons."""
    pool = OFFLINE_LESSONS
    shapes = ([], [pool[0]], [pool[0], pool[3]], [pool[1]], [pool[2]], [pool[1], pool[2]])
    return [Card.of(lessons) for lessons in shapes]


def tools(seed=1):
    return VariationTools(
        OfflineAuthor(), AllowAllJudge(), random.Random(seed), OperatorSchedule(seed), {}
    )


def run(player=None, generations=3, seed=1):
    rules = RunRules(generations, seed, 1, PLENTY)
    return evolve(seeds(), SPLIT, player or FakePlayer(), tools(seed), rules)
