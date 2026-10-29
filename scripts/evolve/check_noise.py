"""Noise check from a run's stored games: the verdict, the numbers and the games it used.

Reads state.json only (no game is played, nothing is spent). The three noise cards are the first
three seed cards; each level pairs their first-seed and second-seed games, and a level where any
of those games is ungraded is left out. The verdict is judged at the games per card selection
used, and the report says how many games per card selection would need.

Usage: check_noise.py --run NAME --pool MAP01,... --root DIR [--selection-games N] [--out FILE]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import run_state  # noqa: E402 - needs the sibling path added above

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit, generation_cases  # noqa: E402
from symbiont.act1.game_fitness import Case, Grade, fitness  # noqa: E402
from symbiont.act1.run_guards import NoiseReport, SpendRoom, noise_check  # noqa: E402

NOISE_CARDS = 3
BLOCK = 4
ROOM_FOR_DOUBLING = SpendRoom(1000.0, 1.0)  # money is not the question here, only the verdict


class IncompleteNoiseGamesError(ValueError):
    """The stored games do not hold both seeds of the noise cards on any level."""


def replays_from(
    games: dict[str, Any], cards: list[Card], first: list[Case], second: list[Case]
) -> dict[str, tuple[tuple[float, float], ...]]:
    """Seed pairs per noise card and level, only for levels where every noise game is graded."""

    def result(card: Card, case: Case) -> Any:
        raw = games.get(run_state.game_key(card.card_id, case))
        if raw is None:
            return None
        return run_state.result_from_json({k: v for k, v in raw.items() if k != "player"})

    def graded(card: Card, case: Case) -> bool:
        found = result(card, case)
        return found is not None and found.grade == Grade.GRADED

    whole = [
        i
        for i in range(BLOCK)
        if all(graded(card, case) for card in cards for case in (first[i], second[i]))
    ]
    if not whole:
        raise IncompleteNoiseGamesError("no level has both seeds graded for every noise card")
    return {
        card.card_id: tuple(
            (fitness(result(card, first[i])), fitness(result(card, second[i]))) for i in whole
        )
        for card in cards
    }


def report_from_state(
    state: dict[str, Any], pool: list[str], seed: int, selection_games: int
) -> NoiseReport:
    """The noise report for generation 0 of a stored run."""
    split = EvolveSplit.exploratory(pool)
    blocks = generation_cases(split, 0, seed, 2)
    first, second = list(blocks[:BLOCK]), list(blocks[BLOCK:])
    cards = [Card.from_json(item) for item in state["seed_cards"][:NOISE_CARDS]]
    replays = replays_from(state["games"], cards, first, second)
    return noise_check(replays, ROOM_FOR_DOUBLING, selection_games)


def report_document(report: NoiseReport) -> dict[str, Any]:
    """Numbers and the verdict, nothing else."""
    return {
        "verdict": report.verdict.value,
        "within_variance": report.within_variance,
        "between_variance": report.between_variance,
        "standard_error": report.standard_error,
        "selection_games": report.selection_games,
        "games_per_mean": report.games_per_mean,
        "pairs_used": report.pairs_used,
        "true_between_variance": report.true_between_variance,
        "games_needed": report.games_needed,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report; write it as JSON when --out is given."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--selection-games", type=int, default=BLOCK)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    state = json.loads((args.root / args.run / "state.json").read_text())
    document = report_document(
        report_from_state(state, args.pool.split(","), args.seed, args.selection_games)
    )
    print(json.dumps(document, indent=1))
    if args.out:
        args.out.write_text(json.dumps(document, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
