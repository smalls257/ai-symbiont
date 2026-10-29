"""Fitness of one played game, and how far along the route to the exit a player got (pure).

Fitness reads game counters and the tagger's mistake count, never the card or the model's words.
Kills are reported but not scored: the owner's anti-goal is a gain from gaming the score, and
Glimmer already fights well (design section 1). An ungraded game (a model error mid-game) has no
fitness: asking for one raises, so a missing game is never scored as a win or a loss.
"""

from dataclasses import dataclass
from enum import StrEnum

from symbiont.act1.move_cuts import CutSetting
from symbiont.act1.navmap import NavMap, NoPath

# Design section 4: 1.0 x exit + 0.5 x route share - 0.02 x mistakes - 0.5 x died.
# [hypothesis] (the weights are a judgment call; the generation-0 fitness check guards them)
EXIT_WEIGHT = 1.0
ROUTE_WEIGHT = 0.5
MISTAKE_WEIGHT = 0.02
DEATH_WEIGHT = 0.5
# Ruling 9 of the plan: remaining distance is measured with every key held, so locked doors do not
# make a level unroutable.
ALL_KEY_COLORS = ("blue", "yellow", "red")


class Grade(StrEnum):
    """Whether a game was played to an end the fitness can read."""

    GRADED = "graded"
    UNGRADED = "ungraded"


class UngradedGameError(ValueError):
    """Fitness was asked of a game that was not graded."""


class NoRouteError(ValueError):
    """A level has no walk from the start to an exit, so route share is undefined."""


@dataclass(frozen=True)
class Case:
    """One game's conditions; the same case is played by every card of a generation."""

    level: str
    seed: int
    skill: int
    cuts: CutSetting


@dataclass(frozen=True)
class GameResult:
    """What one game produced. `kills` is reported only; fitness never reads it."""

    case: Case
    card_id: str
    grade: Grade
    exit_reached: bool
    route_share: float
    mistakes: int
    died: bool
    kills: int
    cut_moves: int
    ungraded_reason: str | None
    # Tagger counts by tag name, as pairs so the result stays hashable; their sum is `mistakes`.
    pains: tuple[tuple[str, int], ...] = ()


def fitness(result: GameResult) -> float:
    """The game's fitness. Raises UngradedGameError for an ungraded game."""
    if result.grade == Grade.UNGRADED:
        raise UngradedGameError(
            f"{result.case.level} seed {result.case.seed} is ungraded: {result.ungraded_reason}"
        )
    return (
        EXIT_WEIGHT * result.exit_reached
        + ROUTE_WEIGHT * result.route_share
        - MISTAKE_WEIGHT * result.mistakes
        - DEATH_WEIGHT * result.died
    )


def route_share(start_units: float, remaining_units: float) -> float:
    """The share of the walk to the exit already covered, clipped to 0 to 1.

    Raises NoRouteError when the start has no distance to cover.
    """
    if start_units <= 0:
        raise NoRouteError(f"the start is {start_units} units from the exit: nothing to cover")
    return min(1.0, max(0.0, 1.0 - remaining_units / start_units))


def remaining_route_units(nav: NavMap, position: tuple[float, float]) -> float:
    """Walking distance from a position to the nearest exit, every key held, every door open.

    Raises NoRouteError, with the nav's own reason, when no exit can be reached.
    """
    found = nav.nearest(position, nav.features("exit"), ALL_KEY_COLORS, closed=frozenset())
    if isinstance(found, NoPath):
        raise NoRouteError(f"no route to the exit: {found.reason}")
    return found[1].length
