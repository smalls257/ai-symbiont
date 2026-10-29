"""Evolve run 2: the small paired design (pure rules; the driver is scripts/evolve/run_duel.py).

A noise phase replays one card on the same cases; an evolution phase gives each arm, every
generation, the current best card and one child to play the same fresh cases, the child written
from the best and worst games of the current best; a final paired test plays three cards on the
same fresh cases, half of them on held-back maps. Every case is fresh: no (level, seed) is used
twice across phases or generations.
"""

import math
import random
import statistics
from collections.abc import Mapping, Sequence

from symbiont.act1.card_genome import Card
from symbiont.act1.evolve_split import EvolveSplit
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness
from symbiont.act1.game_summary import summarize_games
from symbiont.act1.generation import ParentChoice
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting

NOISE_CASES = 5
NOISE_REPLICATES = 5  # 25 games: the same card, the same cases, again and again
GENERATIONS = 5
CASES_PER_GENERATION = 5  # 2 cards x 5 cases x 5 generations = 50 games per arm
FINAL_SELECTION_CASES = 12
FINAL_VALIDATION_CASES = 12  # 3 cards x 24 cases = 72 games
# Seed blocks: far from the generation, validation, cross-level, final and sensitivity seeds.
NOISE_SEED_BASE = 800_000
GENERATION_SEED_BASE = 810_000
GENERATION_SEED_STRIDE = 100
FINAL_SELECTION_SEED_BASE = 820_000
FINAL_VALIDATION_SEED_BASE = 830_000
BOOTSTRAP_DRAWS = 10_000  # as in earlier preregs
Z95 = 1.96


class NotEnoughGamesError(ValueError):
    """Fewer than two graded games: there is no best and worst to compare."""


def _case(level: str, seed: int) -> Case:
    """A normal-condition case: skill 3 and no cut moves."""
    return Case(level, seed, NORMAL_SKILL, CutSetting.NONE)


def noise_cases(split: EvolveSplit, run_seed: int) -> tuple[Case, ...]:
    """Five selection maps, one fresh seed each, for the replay phase."""
    levels = random.Random(f"{run_seed}:noise").sample(split.selection, NOISE_CASES)
    return tuple(_case(level, NOISE_SEED_BASE + i) for i, level in enumerate(levels))


def generation_cases(split: EvolveSplit, generation: int, run_seed: int) -> tuple[Case, ...]:
    """Five distinct selection maps with seeds no other generation uses."""
    levels = random.Random(f"{run_seed}:{generation}:duel").sample(
        split.selection, CASES_PER_GENERATION
    )
    base = GENERATION_SEED_BASE + generation * GENERATION_SEED_STRIDE
    return tuple(_case(level, base + i) for i, level in enumerate(levels))


def final_cases(split: EvolveSplit, run_seed: int) -> tuple[tuple[Case, ...], tuple[Case, ...]]:
    """Fresh seeds on selection maps, and fresh seeds on the held-back (validation) maps."""
    maps = list(split.selection)
    random.Random(f"{run_seed}:final").shuffle(maps)
    selection = tuple(
        _case(maps[i % len(maps)], FINAL_SELECTION_SEED_BASE + i)
        for i in range(FINAL_SELECTION_CASES)
    )
    held_back = tuple(
        _case(split.validation[i % len(split.validation)], FINAL_VALIDATION_SEED_BASE + i)
        for i in range(FINAL_VALIDATION_CASES)
    )
    return selection, held_back


def best_and_worst(results: Sequence[GameResult]) -> tuple[GameResult, GameResult]:
    """The highest- and lowest-fitness graded games (first one on a tie)."""
    graded = [r for r in results if r.grade == Grade.GRADED]
    if len(graded) < 2:
        raise NotEnoughGamesError(f"{len(graded)} graded game(s); a best and a worst need two")
    return max(graded, key=fitness), min(graded, key=fitness)


def trace_summary(result: GameResult) -> str:
    """One game in prose: counts and coarse words only, no map name, score or coordinate."""
    return summarize_games([result], dict(result.pains))


def compare_text(results: Sequence[GameResult]) -> str:
    """What the author reads: the best game's story beside the worst game's."""
    best, worst = best_and_worst(results)
    return f"BEST GAME: {trace_summary(best)} WORST GAME: {trace_summary(worst)}"


def pick_survivor(
    current: tuple[Card, Sequence[float]],
    child: tuple[Card, Sequence[float]],
    choice: ParentChoice,
    coin: random.Random,
) -> Card:
    """The card that carries on: the better mean on this generation's cases, or a coin.

    The coin never looks at a score, so the control arm cannot select by accident. A tie goes to
    the shorter card.
    """
    if choice == ParentChoice.RANDOM:
        return coin.choice([current[0], child[0]])
    scores = {
        current[0].card_id: statistics.fmean(current[1]),
        child[0].card_id: statistics.fmean(child[1]),
    }
    cards = sorted([current[0], child[0]], key=lambda card: (-scores[card.card_id], card.tie_key()))
    return cards[0]


def replay_noise(replicates: Sequence[Sequence[float]]) -> dict[str, float]:
    """Variance of one game replayed on the same case: pooled over the cases.

    `replicates[r][i]` is the fitness of replicate r on case i.
    """
    per_case = list(zip(*replicates, strict=True))
    variance = statistics.fmean(statistics.variance(case) for case in per_case)
    return {
        "replay_variance": variance,
        "replay_sd": math.sqrt(variance),
        "mean": statistics.fmean(v for row in replicates for v in row),
        "cases": float(len(per_case)),
        "replicates": float(len(replicates)),
    }


def expected_half_width(replay_variance: float, cases: int) -> float:
    """95% half-width of a paired mean difference over `cases` cases, one game per card per case."""
    return Z95 * math.sqrt(2 * replay_variance / cases)


def paired_groups(
    scores: Mapping[str, Mapping[Case, float]], first: str, second: str
) -> dict[str, list[float]]:
    """Per-map lists of (first - second) fitness over the cases both cards played."""
    groups: dict[str, list[float]] = {}
    for case, value in scores[first].items():
        if case in scores[second]:
            groups.setdefault(case.level, []).append(value - scores[second][case])
    return groups


def paired_interval(groups: Mapping[str, Sequence[float]], seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap of the mean difference, resampling maps with their games."""
    levels = sorted(groups)
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_DRAWS):
        drawn = [value for level in rng.choices(levels, k=len(levels)) for value in groups[level]]
        means.append(statistics.fmean(drawn))
    means.sort()
    return means[int(0.025 * BOOTSTRAP_DRAWS)], means[int(0.975 * BOOTSTRAP_DRAWS) - 1]


def decision_word(low: float, high: float) -> str:
    """Better if the interval is above 0, worse if below, else tie."""
    if low > 0:
        return "better"
    return "worse" if high < 0 else "tie"
