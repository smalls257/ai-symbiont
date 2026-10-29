"""Fitness check on real generation-0 games: gaming policies must score below the empty card.

Stand still, fire in place and spin play the same four generation-0 cases as the empty card (local,
free); any of them at or above the empty card's Spark mean fails the check and blocks the prereg
until the fitness weights are revisited. Writes counts and labels only to the results file.

Usage: check_fitness.py --run NAME --pool MAP01,... --root DIR --wad WAD --out FILE.json
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import play_case  # noqa: E402 - needs the sibling path added above
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit, generation_cases  # noqa: E402
from symbiont.act1.game_fitness import Case, Grade, fitness  # noqa: E402

GAMING_POLICIES = ("stand_still", "fire_in_place", "spin")
SCHEMA = "evolve-gen0-v1"
BLOCK = 4  # one seed on each of the generation's four levels


class GamingBeatsEmptyError(RuntimeError):
    """A gaming policy scored at or above the empty card."""


def gaming_means(cases: list[Case], wad: Path, workers: int, episodes: Path) -> dict[str, float]:
    """Mean fitness of each gaming policy with the empty card on the cases."""
    means = {}
    for name in GAMING_POLICIES:
        setup = play_case.EngineSetup(wad=wad, episodes=episodes / name, workers=workers)
        player = play_case.EnginePlayer(spark_players.ScriptedPlayers(name), setup)
        results: list = []
        keep = results.append
        player.play_many(
            [(Card.of([]), c) for c in cases], lambda _card, _case, result, keep=keep: keep(result)
        )
        means[name] = statistics.fmean(fitness(r) for r in results if r.grade == Grade.GRADED)
    return means


def reused_gaming(path: Path) -> dict[str, float]:
    """The gaming policies' means from an earlier results file (the games are not replayed)."""
    rows = json.loads(path.read_text())["rows"]
    return {row["label"]: row["mean_fitness"] for row in rows if row["role"] == "floor"}


def require_below(empty_mean: float, means: dict[str, float]) -> None:
    """Raises GamingBeatsEmptyError naming every policy at or above the empty card."""
    bad = {name: m for name, m in means.items() if m >= empty_mean}
    if bad:
        shown = ", ".join(f"{n} {m:.3f}" for n, m in sorted(bad.items()))
        raise GamingBeatsEmptyError(f"at or above the empty card ({empty_mean:.3f}): {shown}")


def card_means(games: dict[str, Any], cases: list[Case]) -> dict[str, float]:
    """Mean fitness per card over its graded games on `cases`, from the run's state file."""
    wanted = {run_state.game_key("", c).split("|", 1)[1] for c in cases}
    per_card: dict[str, list[float]] = {}
    for key, raw in games.items():
        card_id, rest = key.split("|", 1)
        if rest in wanted:
            result = run_state.result_from_json({k: v for k, v in raw.items() if k != "player"})
            if result.grade == Grade.GRADED:
                per_card.setdefault(card_id, []).append(fitness(result))
    return {card: statistics.fmean(values) for card, values in per_card.items()}


def results_document(
    empty_mean: float, gaming: dict[str, float], cards: dict[str, float], noise: dict[str, Any]
) -> dict[str, Any]:
    """Counts, ids and labels only: scripted policies are floors, cards are references."""
    rows = [{"label": "empty card", "role": "reference", "mean_fitness": empty_mean}]
    rows += [{"label": n, "role": "floor", "mean_fitness": m} for n, m in gaming.items()]
    return {
        "schema": SCHEMA,
        "label": "exploratory generation 0, Muse Spark at low reasoning [measured]",
        "rows": rows,
        "card_means": {card: round(mean, 4) for card, mean in sorted(cards.items())},
        "fitness_spread": round(max(cards.values()) - min(cards.values()), 4),
        "noise": noise,
        "gaming_check": "passed",
    }


def main(argv: list[str] | None = None) -> int:
    """Run the check; exit 1 with the numbers when a gaming policy beats the empty card."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--noise-from", type=Path, help="noise report JSON (check_noise.py)")
    parser.add_argument("--gaming-from", type=Path, help="reuse the floor rows of an earlier file")
    args = parser.parse_args(argv)
    directory = args.root / args.run
    state = json.loads((directory / "state.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    split = EvolveSplit.exploratory(args.pool.split(","))
    cases = list(generation_cases(split, 0, args.seed, 1))[:BLOCK]
    cards = card_means(state["games"], cases)
    empty = Card.of([]).card_id
    gaming = (
        reused_gaming(args.gaming_from)
        if args.gaming_from
        else gaming_means(cases, args.wad, args.workers, directory / "episodes")
    )
    noise = json.loads(args.noise_from.read_text()) if args.noise_from else summary["noise"]
    print(f"empty card {cards[empty]:.3f}; " + "; ".join(f"{n} {m:.3f}" for n, m in gaming.items()))
    require_below(cards[empty], gaming)
    args.out.write_text(
        json.dumps(results_document(cards[empty], gaming, cards, noise), indent=1) + "\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GamingBeatsEmptyError as error:
        print(f"FITNESS CHECK FAILED: {error}")
        sys.exit(1)
