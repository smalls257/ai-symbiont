"""Run guards: the checks that stop a run from selecting on luck or training on the test (pure).

Each stop carries the numbers that triggered it, so a stopped run explains itself. They return a
value (the noise report, the gap verdict) or raise a named error; none of them returns a quiet
default.
"""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from symbiont.act1.game_fitness import GameResult, Grade
from symbiont.act1.generality import Verdict

# Doubling the games must fit under the cap with a margin, or the run stops (plan T9).
SPEND_MARGIN = 1.2  # [hypothesis] (the plan's 20% margin)
GAMES_PER_MEAN = 4  # a generation's training mean and the validation mean are over 4 games each
# Design section 9: more than 10% ungraded games in a generation stops the run.
UNGRADED_LIMIT = 0.10  # [hypothesis] (design setting)
# Design section 9: generality rejections above half of a generation mean the prompt needs fixing.
REJECTION_LIMIT = 0.5


class TooManyUngradedError(RuntimeError):
    """More games in a generation ended ungraded than the design allows."""


class MutationPromptError(RuntimeError):
    """The generality filter rejected more than half of a generation's children."""


class NoiseVerdict(StrEnum):
    """What the generation-0 noise check decides."""

    SELECT = "select"
    DOUBLE_GAMES = "double_games"
    STOP = "stop"


@dataclass(frozen=True)
class SpendRoom:
    """What is left under the cap, and what playing every game twice would cost."""

    remaining_usd: float
    doubling_cost_usd: float

    def fits_doubling(self) -> bool:
        """Whether doubling fits with the 20% margin."""
        return self.doubling_cost_usd * SPEND_MARGIN <= self.remaining_usd


@dataclass(frozen=True)
class NoiseReport:
    """The two spreads, the verdict and the standard error of a four-game mean."""

    verdict: NoiseVerdict
    within_variance: float
    between_variance: float
    standard_error: float


def noise_check(
    replays: Mapping[str, tuple[tuple[float, float], ...]], spend_room: SpendRoom
) -> NoiseReport:
    """Seed noise of a card's mean against card differences, from the same games.

    `replays` holds one seed pair per card and level. The standard error is the spread of all
    games over the square root of 4, the size of a mean.
    """
    pairs = [pair for rows in replays.values() for pair in rows]
    within = statistics.fmean(statistics.variance(pair) for pair in pairs)
    card_means = [statistics.fmean(v for pair in rows for v in pair) for rows in replays.values()]
    between = statistics.variance(card_means)
    every_game = [value for pair in pairs for value in pair]
    standard_error = statistics.stdev(every_game) / GAMES_PER_MEAN**0.5
    games_per_card = 2 * len(next(iter(replays.values())))
    verdict = _noise_verdict(within / games_per_card, between, spend_room)
    return NoiseReport(verdict, within, between, standard_error)


def _noise_verdict(within_of_mean: float, between: float, spend_room: SpendRoom) -> NoiseVerdict:
    """SELECT when card means differ more than seed noise moves a mean; else double or stop."""
    if within_of_mean < between:
        return NoiseVerdict.SELECT
    return NoiseVerdict.DOUBLE_GAMES if spend_room.fits_doubling() else NoiseVerdict.STOP


class GapDecision(StrEnum):
    """Whether evolution goes on."""

    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True)
class GapVerdict:
    """The gap watch's decision; `last_good_generation` is set on STOP."""

    decision: GapDecision
    last_good_generation: int | None
    detail: str


@dataclass
class GapWatch:
    """Watches training mean minus validation mean per generation (plan ruling 4).

    A gap "widens" when it rises by more than `threshold` (the standard error of a four-game
    mean from the noise check); two rises in a row stop evolution at the generation before the
    first rise.
    """

    threshold: float
    gaps: list[tuple[int, float]] = field(default_factory=list)

    def record(self, generation: int, training_mean: float, validation_mean: float) -> None:
        """Log one generation's gap."""
        self.gaps.append((generation, training_mean - validation_mean))

    def verdict(self) -> GapVerdict:
        """STOP at the first two consecutive rises, else CONTINUE."""
        rose = [
            later[1] - earlier[1] > self.threshold
            for earlier, later in zip(self.gaps, self.gaps[1:], strict=False)
        ]
        for index in range(len(rose) - 1):
            if rose[index] and rose[index + 1]:
                first, second, third = self.gaps[index : index + 3]
                detail = (
                    f"gap rose {first[1]:.2f} -> {second[1]:.2f} -> {third[1]:.2f} over "
                    f"generations {first[0]} to {third[0]}; threshold {self.threshold:.2f}"
                )
                return GapVerdict(GapDecision.STOP, first[0], detail)
        return GapVerdict(GapDecision.CONTINUE, None, "gap has not risen twice in a row")


def require_graded_share(results: Sequence[GameResult], limit: float = UNGRADED_LIMIT) -> None:
    """Raises TooManyUngradedError when the ungraded share of games is above the limit."""
    ungraded = sum(r.grade == Grade.UNGRADED for r in results)
    if results and ungraded / len(results) > limit:
        raise TooManyUngradedError(
            f"{ungraded} of {len(results)} games ungraded; the limit is {limit:.0%}"
        )


def require_rejection_share(verdicts: Sequence[Verdict], limit: float = REJECTION_LIMIT) -> None:
    """Raises MutationPromptError when more than `limit` of the children were rejected."""
    rejected = sum(not v.general for v in verdicts)
    if verdicts and rejected / len(verdicts) > limit:
        raise MutationPromptError(
            f"{rejected} of {len(verdicts)} children rejected by the generality filter; "
            f"the limit is {limit:.0%}: fix the mutation prompt before continuing"
        )
