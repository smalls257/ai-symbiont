"""Parent selection by epsilon-lexicase, and the elites a generation keeps (pure).

Averaging fitness over cases hides a card that is excellent on one kind of level; lexicase keeps
such specialists alive by filtering the pool one case at a time in random order [established]
(La Cava et al., 2016, epsilon-lexicase with the median absolute deviation as epsilon). A case in
which any card has an ungraded game is dropped for every card and listed: filling the hole with a
default would score a model error as a win or a loss.
"""

import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness

TieKey = Callable[[str], tuple[int, str]]


class NoGradableCaseError(ValueError):
    """Every case had an ungraded game: there is nothing to select on."""


class IncompleteTableError(ValueError):
    """A card has no game on a case that other cards played: the cards are not paired."""


@dataclass(frozen=True)
class FitnessTable:
    """Mean fitness per (card, case) over the cases every card played to a graded end."""

    cards: tuple[str, ...]
    cases: tuple[Case, ...]
    scores: Mapping[tuple[str, Case], float]
    dropped_cases: tuple[Case, ...]

    @classmethod
    def of(cls, results: Sequence[GameResult]) -> "FitnessTable":
        """Build the table. Raises NoGradableCaseError or IncompleteTableError (a missing game)."""
        cards = tuple(dict.fromkeys(r.card_id for r in results))
        cases = tuple(dict.fromkeys(r.case for r in results))
        dropped = {r.case for r in results if r.grade == Grade.UNGRADED}
        kept = tuple(c for c in cases if c not in dropped)
        if not kept:
            raise NoGradableCaseError(f"all {len(cases)} case(s) had an ungraded game")
        games = _games_by_card_and_case(results, set(kept))
        _require_paired(cards, kept, games)
        scores = {key: statistics.fmean(values) for key, values in games.items()}
        return cls(cards, kept, scores, tuple(c for c in cases if c in dropped))


def _games_by_card_and_case(
    results: Sequence[GameResult], kept: set[Case]
) -> dict[tuple[str, Case], list[float]]:
    """Fitness of every game on a kept case, grouped by card and case."""
    games: dict[tuple[str, Case], list[float]] = defaultdict(list)
    for result in results:
        if result.case in kept:
            games[(result.card_id, result.case)].append(fitness(result))
    return games


def _require_paired(
    cards: tuple[str, ...], cases: tuple[Case, ...], games: Mapping[tuple[str, Case], object]
) -> None:
    """Raises IncompleteTableError naming the first card without a game on a kept case."""
    for card in cards:
        for case in cases:
            if (card, case) not in games:
                raise IncompleteTableError(
                    f"card {card} has no game on {case.level} seed {case.seed}"
                )


def _epsilon(table: FitnessTable, case: Case) -> float:
    """Median absolute deviation of the cards' scores on one case."""
    values = [table.scores[(card, case)] for card in table.cards]
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def _one_parent(table: FitnessTable, rng: random.Random, tie_key: TieKey) -> str:
    """One lexicase draw: filter by shuffled cases, then shorter card, then chance (not the id)."""
    pool = list(table.cards)
    for case in rng.sample(table.cases, len(table.cases)):
        if len(pool) == 1:
            break
        best = max(table.scores[(card, case)] for card in pool)
        floor = best - _epsilon(table, case)
        pool = [card for card in pool if table.scores[(card, case)] >= floor]
    shortest = min(tie_key(card)[0] for card in pool)
    return rng.choice([card for card in pool if tie_key(card)[0] == shortest])


def select_parents(
    table: FitnessTable, count: int, rng: random.Random, tie_key: TieKey
) -> tuple[str, ...]:
    """`count` parents by epsilon-lexicase; survivors of every case: shorter card wins, then rng."""
    return tuple(_one_parent(table, rng, tie_key) for _ in range(count))


def elites(table: FitnessTable, count: int, tie_key: TieKey) -> tuple[str, ...]:
    """The `count` cards with the best mean fitness; equal means: the shorter card first."""

    def mean(card: str) -> float:
        return statistics.fmean(table.scores[(card, case)] for case in table.cases)

    ranked = sorted(table.cards, key=lambda card: (-mean(card), tie_key(card)))
    return tuple(ranked[:count])


def random_parents(cards: Sequence[str], count: int, rng: random.Random) -> tuple[str, ...]:
    """The no-selection arm's parents: uniform draws that ignore fitness."""
    return tuple(rng.choice(cards) for _ in range(count))
