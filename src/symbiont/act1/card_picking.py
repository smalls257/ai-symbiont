"""Which card an arm sends to the final test, and which of its lessons earned their place (pure).

One rule serves both arms and reads training games only, so validation stays a clean check. A
lesson that only helps on the level that produced it is the memorizing-card failure; each kept
lesson must do at least as well with it as without on a level it was not born on.
"""

import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.act1.card_genome import Card
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting

# A card that arrived in the last generation has played 4 games, not 8: its mean is a thinner
# sample than the elites' and a lucky draw would win. Both generations' 4 cases are required.
MIN_PICK_GAMES = 8
TieKey = Callable[[str], tuple[int, str]]
# Cross-level games draw seeds here, apart from generation draws and the final test's 1001, 1002.
CROSS_LEVEL_SEEDS = (3000, 3999)


class GameRole(StrEnum):
    """What a game was played for."""

    SELECTION = "selection"
    VALIDATION = "validation"


@dataclass(frozen=True)
class PlayedGame:
    """A result with the generation and role it was played in."""

    result: GameResult
    generation: int
    role: GameRole


class ValidationUsedForPickingError(ValueError):
    """A validation game was offered to the picking rule."""


class NoGamesToPickError(ValueError):
    """No graded selection game of any card fell in the picked generations."""


class NoSharedCaseError(ValueError):
    """A lesson's ablation and the full card share no graded case: nothing to compare."""


class NotEnoughLevelsError(ValueError):
    """Fewer selection levels remain than the check needs, once source levels are excluded."""


def pick_best(
    games: Sequence[PlayedGame], last_generations: tuple[int, int], tie_key: TieKey
) -> str:
    """The card with the highest mean fitness over its graded games in the two generations.

    Only a card with at least MIN_PICK_GAMES graded games in them is eligible.

    Raises ValidationUsedForPickingError if any validation game is passed in at all.
    """
    for played in games:
        if played.role == GameRole.VALIDATION:
            raise ValidationUsedForPickingError(
                f"validation game on {played.result.case.level} offered to picking"
            )
    scores: dict[str, list[float]] = defaultdict(list)
    for played in games:
        if played.generation in last_generations and played.result.grade == Grade.GRADED:
            scores[played.result.card_id].append(fitness(played.result))
    scores = {card: values for card, values in scores.items() if len(values) >= MIN_PICK_GAMES}
    if not scores:
        raise NoGamesToPickError(
            f"no card has {MIN_PICK_GAMES} graded games in generations {last_generations}"
        )
    return min(scores, key=lambda card: (-statistics.fmean(scores[card]), tie_key(card)))


def cross_level_cases(
    card: Card, pool: Sequence[str], rng: random.Random, count: int = 2
) -> tuple[Case, ...]:
    """Normal-condition cases on selection levels that no lesson of the card came from."""
    sources = {lesson.source_level for lesson in card.lessons}
    eligible = [level for level in pool if level not in sources]
    if len(eligible) < count:
        raise NotEnoughLevelsError(f"{len(eligible)} eligible level(s); the check needs {count}")
    return tuple(
        Case(level, rng.randint(*CROSS_LEVEL_SEEDS), NORMAL_SKILL, CutSetting.NONE)
        for level in rng.sample(eligible, count)
    )


def _graded_by_case(results: Sequence[GameResult]) -> dict[Case, float]:
    """Mean fitness per case over the graded games."""
    by_case: dict[Case, list[float]] = defaultdict(list)
    for result in results:
        if result.grade == Grade.GRADED:
            by_case[result.case].append(fitness(result))
    return {case: statistics.fmean(values) for case, values in by_case.items()}


def _earns_its_place(with_card: Mapping[Case, float], without: Mapping[Case, float]) -> bool:
    """The full card's mean is at least the ablated card's mean, on the shared cases."""
    shared = [case for case in with_card if case in without]
    if not shared:
        raise NoSharedCaseError("the card and its ablation share no graded case to compare on")
    return statistics.fmean(with_card[c] for c in shared) >= statistics.fmean(
        without[c] for c in shared
    )


def keep_lessons(
    card: Card, with_card: Sequence[GameResult], without: Mapping[int, Sequence[GameResult]]
) -> Card:
    """Drop each lesson whose removal raised the mean on the cases both versions played.

    `without[i]` holds the games of the card with lesson i removed. Ablations are one lesson at
    a time. Raises ValueError for a lesson with no ablation games; cutting all gives the empty card.
    """
    full = _graded_by_case(with_card)
    kept = []
    for index, lesson in enumerate(card.lessons):
        if index not in without:
            raise ValueError(f"lesson {index} has no ablation games")
        if _earns_its_place(full, _graded_by_case(without[index])):
            kept.append(lesson)
    return Card.of(kept)
