"""Exploratory: "one move per reply" against no lesson on fresh generated maps, at 48 decisions.

No prereg and no claim: the maps are listed in a committed declaration, the cases are seed-major
so a stop at any time leaves balanced arms, and the report is counts and means only.

Usage: fresh_onemove.py play|report --maps FILE --wads DIR [--seeds N --workers N --decisions N]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

import script_paths

script_paths.add_script_dirs()

import frozen_cards  # noqa: E402 - needs the sibling path added above
import held_out_cases  # noqa: E402
import held_out_test  # noqa: E402
import paired_traces  # noqa: E402
import play_case  # noqa: E402
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.game_fitness import Case, Grade, fitness  # noqa: E402
from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError  # noqa: E402

RUN = "fresh48"
RUN_CAP = 10.0  # dollars for this run's ledger name
FIRST_SEED = 4101  # clear of every earlier block (held-out test 4001 to 4009)
ARMS = {"none": frozen_cards.NO_CARD, "one_move": paired_traces.ONE_MOVE}


def fresh_cases(maps: list[str], seeds: int) -> tuple[Case, ...]:
    """Seed-major cases: every map at one seed before any map at the next."""
    return held_out_cases.cases_on(tuple(maps), tuple(range(FIRST_SEED, FIRST_SEED + seeds)))


def arm_player(arm: str, args: argparse.Namespace, maps: list[str]) -> run_state.ResumingPlayer:
    """A resumable player for one arm in its own run directory."""
    directory = args.root / f"{RUN}-{arm}"
    store = run_state.RunStore(directory)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"low; {args.decisions} decisions; arm {arm}",
        }  # fmt: skip
    )
    replies = spark_players.SparkPlayers(
        run=RUN, run_cap=RUN_CAP, effort=Effort.LOW, max_tokens=spark_players.DEFAULT_MAX_TOKENS
    )
    setup = play_case.EngineSetup(
        wad=args.freedoom, episodes=directory / "episodes", decisions=args.decisions,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers, mode=play_case.RunMode.EXPLORATORY_LISTED,
        final_levels=frozenset(maps), loader=held_out_cases.LevelLoader(args.wads),
    )  # fmt: skip
    return run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)


def play(args: argparse.Namespace) -> None:
    """Both arms on every case, batch by batch; resumable."""
    maps = json.loads(args.maps.read_text())["kept"]
    players = {arm: arm_player(arm, args, maps) for arm in ARMS}
    cases = fresh_cases(maps, args.seeds)
    for start in range(0, len(cases), args.batch):
        for arm, player in players.items():
            pairs = [(ARMS[arm], case) for case in cases[start : start + args.batch]]
            held_out_test.play_until_graded(player, pairs)


def report(args: argparse.Namespace) -> None:
    """Exits, deaths, alive at the end and mean fitness per arm, on cases graded in both arms."""
    games = {arm: graded_games(args.root, arm) for arm in ARMS}
    common = sorted(
        set.intersection(*(set(g) for g in games.values())),
        key=lambda each: (each.seed, each.level),
    )
    out = {"cases": len(common)}
    for arm, found in games.items():
        results = [found[case] for case in common]
        out[arm] = {
            "exits": sum(r.exit_reached for r in results),
            "deaths": sum(r.died and not r.exit_reached for r in results),
            "alive_at_end": sum(not r.died and not r.exit_reached for r in results),
            "mean_fitness": round(statistics.fmean(fitness(r) for r in results), 3),
        }
    diffs = [fitness(games["one_move"][case]) - fitness(games["none"][case]) for case in common]
    out["one_move_minus_none"] = {
        "mean": round(statistics.fmean(diffs), 3),
        "se": round(statistics.stdev(diffs) / len(diffs) ** 0.5, 3),
    }
    print(json.dumps(out))


def graded_games(root: Path, arm: str) -> dict[Case, object]:
    """Graded stored games of one arm."""
    state = json.loads((root / f"{RUN}-{arm}" / "state.json").read_text())["games"]
    results = (run_state.result_from_json(held_out_test.drop_player(g)) for g in state.values())
    return {r.case: r for r in results if r.grade == Grade.GRADED}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("play", "report"))
    parser.add_argument("--maps", type=Path, required=True)
    parser.add_argument("--wads", type=Path, required=True)
    parser.add_argument("--freedoom", type=Path, default=Path("data/freedoom"))
    parser.add_argument("--root", type=Path, default=Path.home() / "symbiont-runs" / "evolve")
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--decisions", type=int, default=48)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args(argv)
    {"play": play, "report": report}[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
