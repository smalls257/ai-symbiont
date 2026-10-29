"""A prose summary of a card's games for the lesson author (pure).

Built from counters and tagger counts, never raw logs: the author reads sentences with counts of
games and coarse words for progress, and no map name, coordinate, score or float, so a summary
cannot hand the author a landmark to write into a lesson.
"""

import statistics
from collections.abc import Mapping, Sequence

from symbiont.act1.game_fitness import GameResult, Grade
from symbiont.act1.game_pains import GamePain

# The builder's call (the design leaves wording open): what each tag means in plain words.
PAIN_PHRASES = {
    GamePain.WASTED_MOVE: "moves that changed nothing",
    GamePain.ROOM_RECHECKED: "turns in rooms already checked",
    GamePain.WALL_BUMP: "walks into walls",
    GamePain.ROOM_REENTERED: "returns to rooms already left",
}
NO_PROGRESS_BELOW = 0.05  # mean route share under this reads as "none"
MOST_FROM = 0.5  # mean route share from this reads as "most"


class NoGradedGamesError(ValueError):
    """A summary was asked of games none of which was graded."""


def _exit_sentence(graded: Sequence[GameResult]) -> str:
    """How many games reached the exit, in words and counts of games."""
    missed = sum(not game.exit_reached for game in graded)
    if missed == 0:
        return f"In all {len(graded)} games the exit was reached."
    return f"In {missed} of {len(graded)} games the exit was not reached."


def _route_sentence(graded: Sequence[GameResult]) -> str | None:
    """A coarse word for how far the games that missed the exit got; None if none missed."""
    missed = [game.route_share for game in graded if not game.exit_reached]
    if not missed:
        return None
    mean = statistics.fmean(missed)
    word = "none" if mean < NO_PROGRESS_BELOW else "most" if mean >= MOST_FROM else "some"
    return f"In the games that missed the exit the player covered {word} of the route."


def _mistake_sentence(pains: Mapping[str, int]) -> str:
    """Name the most common tagged mistake, or say there was none."""
    counts = {GamePain(name): count for name, count in pains.items()}
    top = max(counts, key=lambda pain: counts[pain], default=None)
    if top is None or counts[top] == 0:
        return "No mistakes were tagged."
    return f"The most common mistake was {PAIN_PHRASES[top]}."


def _death_sentence(graded: Sequence[GameResult]) -> str | None:
    """How many games ended in death, or None."""
    died = sum(game.died for game in graded)
    if died == 0:
        return None
    return "One game ended in death." if died == 1 else f"{died} games ended in death."


def summarize_games(results: Sequence[GameResult], pains: Mapping[str, int]) -> str:
    """Sentences about the graded games; `pains` maps tag names to counts.

    Raises NoGradedGamesError for no graded game and ValueError for an unknown tag name.
    """
    graded = [game for game in results if game.grade == Grade.GRADED]
    if not graded:
        raise NoGradedGamesError("every game was ungraded: nothing to summarize")
    parts = [
        _exit_sentence(graded),
        _route_sentence(graded),
        _mistake_sentence(pains),
        _death_sentence(graded),
    ]
    return " ".join(part for part in parts if part)
