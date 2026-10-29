"""Evolve run 2: the small paired design (pure rules; the driver is scripts/evolve/run_duel.py).

A noise phase (run 2) replays one card on the same cases; an evolution phase gives each arm, every
generation, the current best card and one child to play the same fresh cases, the child written
from the best and worst games of the current best; a final paired test plays three cards on the
same fresh cases, half of them on held-back maps. Every case is fresh: no (level, seed) is used
twice across phases or generations.
"""

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.act1.card_genome import Card
from symbiont.act1.evolve_split import EvolveSplit
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness
from symbiont.act1.game_summary import summarize_games
from symbiont.act1.generation import ParentChoice
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting


@dataclass(frozen=True)
class DuelPlan:
    """The sizes and seed blocks of one run of the paired design.

    Seed blocks are far from the generation, validation, cross-level, final and sensitivity seeds
    and from each other, so no (level, seed) is played by two phases or two runs.
    """

    name: str  # prefix of the run's state directories and ledger names
    generations: int
    cases_per_generation: int
    children_per_generation: int
    noise_cases: int
    noise_replicates: int
    final_selection_cases: int
    final_validation_cases: int
    noise_seed: int
    generation_seed: int
    generation_stride: int
    final_selection_seed: int
    final_validation_seed: int


# Run 2: 25 noise games, 2 cards x 5 cases x 5 generations = 50 games an arm, 3 x 24 = 72 final.
RUN2 = DuelPlan("duel", 5, 5, 1, 5, 5, 12, 12, 800_000, 810_000, 100, 820_000, 830_000)
# Run 3: no noise phase (run 2's replay variance is reused). Per arm 4 generations x (1 current +
# 3 children) x 10 cases = 160 games; random-operator children 3 x 4 x 10 = 120; final 3 x 40 = 120.
RUN3 = DuelPlan("duel3", 4, 10, 3, 0, 0, 20, 20, 900_000, 910_000, 1_000, 920_000, 930_000)
PLANS = {plan.name: plan for plan in (RUN2, RUN3)}
NOISE_CASES = RUN2.noise_cases
NOISE_REPLICATES = RUN2.noise_replicates
GENERATIONS = RUN2.generations
CASES_PER_GENERATION = RUN2.cases_per_generation
FINAL_SELECTION_CASES = RUN2.final_selection_cases
FINAL_VALIDATION_CASES = RUN2.final_validation_cases
BOOTSTRAP_DRAWS = 10_000  # as in earlier preregs
Z95 = 1.96


class NotEnoughGamesError(ValueError):
    """Fewer than two graded games: there is no best and worst to compare."""


def _case(level: str, seed: int) -> Case:
    """A normal-condition case: skill 3 and no cut moves."""
    return Case(level, seed, NORMAL_SKILL, CutSetting.NONE)


def _levels(maps: Sequence[str], count: int, rng: random.Random) -> list[str]:
    """`count` maps: distinct ones while there are enough, then shuffled rounds of all of them."""
    if count <= len(maps):
        return rng.sample(list(maps), count)
    levels: list[str] = []
    while len(levels) < count:
        levels += rng.sample(list(maps), len(maps))
    return levels[:count]


def noise_cases(split: EvolveSplit, run_seed: int, plan: DuelPlan = RUN2) -> tuple[Case, ...]:
    """Selection maps, one fresh seed each, for the replay phase."""
    levels = _levels(split.selection, plan.noise_cases, random.Random(f"{run_seed}:noise"))
    return tuple(_case(level, plan.noise_seed + i) for i, level in enumerate(levels))


def generation_cases(
    split: EvolveSplit, generation: int, run_seed: int, plan: DuelPlan = RUN2
) -> tuple[Case, ...]:
    """The generation's selection cases, with seeds no other generation uses."""
    rng = random.Random(f"{run_seed}:{generation}:duel")
    levels = _levels(split.selection, plan.cases_per_generation, rng)
    base = plan.generation_seed + generation * plan.generation_stride
    return tuple(_case(level, base + i) for i, level in enumerate(levels))


def final_cases(
    split: EvolveSplit, run_seed: int, plan: DuelPlan = RUN2
) -> tuple[tuple[Case, ...], tuple[Case, ...]]:
    """Fresh seeds on selection maps, and fresh seeds on the held-back (validation) maps."""
    maps = list(split.selection)
    random.Random(f"{run_seed}:final").shuffle(maps)
    selection = tuple(
        _case(maps[i % len(maps)], plan.final_selection_seed + i)
        for i in range(plan.final_selection_cases)
    )
    held_back = tuple(
        _case(split.validation[i % len(split.validation)], plan.final_validation_seed + i)
        for i in range(plan.final_validation_cases)
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


def pick_among(
    candidates: Sequence[tuple[Card, Sequence[float]]], choice: ParentChoice, coin: random.Random
) -> Card:
    """The card that carries on among several: the best mean, or one drawn by a blind coin."""
    if choice == ParentChoice.RANDOM:
        return coin.choice([card for card, _ in candidates])
    means = {card.card_id: statistics.fmean(scores) for card, scores in candidates}
    return sorted(
        (card for card, _ in candidates), key=lambda card: (-means[card.card_id], card.tie_key())
    )[0]


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


def beats_parent(child_scores: Sequence[float], parent_scores: Sequence[float]) -> bool:
    """A child beats its parent when its mean on the same cases is strictly higher."""
    return statistics.fmean(child_scores) > statistics.fmean(parent_scores)


def wilson_interval(wins: int, total: int) -> tuple[float, float, float]:
    """The share of wins and its 95% Wilson interval (it behaves with a handful of trials)."""
    if total == 0:
        raise NotEnoughGamesError("no children to score")
    share = wins / total
    denominator = 1 + Z95**2 / total
    center = (share + Z95**2 / (2 * total)) / denominator
    margin = Z95 * math.sqrt(share * (1 - share) / total + Z95**2 / (4 * total**2)) / denominator
    return share, max(0.0, center - margin), min(1.0, center + margin)


def child_share(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """How many children won of rows with `child_mean` and `current_mean`, with a share interval."""
    wins = sum(row["child_mean"] > row["current_mean"] for row in rows)
    share, low, high = wilson_interval(wins, len(rows))
    gains = [row["child_mean"] - row["current_mean"] for row in rows]
    return {
        "children": float(len(rows)),
        "beat_parent": float(wins),
        "share": share,
        "low": low,
        "high": high,
        "mean_gain": statistics.fmean(gains),
    }
