"""Exploratory: do more decisions per game open headroom? Spark, no card, the sensitivity cases.

Plays the same twelve training cases at 16, 32 and 48 decisions (fresh games at each depth, so
the comparison is paired by case), then replays each logged game without a model call to split
its mistakes by whether the reply held one move or several.

Usage: decision_depth.py --root DIR --wad WAD --out FILE [--depths 16,32,48] [--workers N]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import card_sensitivity  # noqa: E402 - needs the sibling path added above
import play_case  # noqa: E402
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.episode import RunLog, load_run_log, run_episode  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.game_pains import tag_pains  # noqa: E402
from symbiont.act1.glimmer import Reply  # noqa: E402
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort, SparkApiError, SparkReplyError  # noqa: E402

NO_CARD = Card.of([])
RUN_CAP = 0.6  # dollars per depth: 12 games of up to 48 decisions at about 0.005 a game of 16
SCHEMA = "evolve-depth-v1"


def play_depth(depth: int, args: argparse.Namespace) -> list[GameResult]:
    """The twelve cases at one decision count; resumable through the run's state file."""
    run = f"depth-{depth}"
    store = run_state.RunStore(args.root / run)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"low; current; {depth} decisions",
        }  # fmt: skip
    )
    replies = spark_players.SparkPlayers(
        run=run, run_cap=RUN_CAP, effort=Effort.LOW, max_tokens=DEFAULT_MAX_TOKENS
    )
    setup = play_case.EngineSetup(
        wad=args.wad,
        episodes=args.root / run / "episodes",
        decisions=depth,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
    )
    player = run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)
    found: list[GameResult] = []
    cases = card_sensitivity.sensitivity_cases()
    player.play_many(
        [(NO_CARD, case) for case in cases], lambda _card, _case, result: found.append(result)
    )
    return found


def depth_stats(results: list[GameResult]) -> dict[str, Any]:
    """Exit rate, route share, mistakes and fitness over the graded games."""
    graded = [r for r in results if r.grade == Grade.GRADED]
    scores = [fitness(r) for r in graded]
    return {
        "games": len(graded),
        "ungraded": len(results) - len(graded),
        "exits": sum(r.exit_reached for r in graded),
        "deaths": sum(r.died for r in graded),
        "route_share": round(statistics.fmean(r.route_share for r in graded), 3),
        "mistakes": round(statistics.fmean(r.mistakes for r in graded), 2),
        "fitness": round(statistics.fmean(scores), 3),
        "fitness_sd": round(statistics.stdev(scores), 3),
    }


def move_lines(reply: str) -> int:
    """How many non-empty lines a reply holds: each is one scripted move."""
    return sum(1 for line in reply.splitlines() if line.strip())


def attribute_mistakes(log: Path, case: Case, args: argparse.Namespace) -> dict[str, int]:
    """Replay a logged game (no model) and count its tagged mistakes by reply shape."""
    decisions = load_run_log(log)
    game, knowledge, rooms = play_case.load_case_level(args.wad, case)
    runs: list[Any] = []
    calls = [0]

    def reply(_prompt: str) -> Reply:
        call = decisions[calls[0]]
        calls[0] += 1
        return Reply(call.reply, "stop", 0)

    try:
        game.new_episode()
        run_episode(game, reply, len(decisions), RunLog(on_move=runs.append), knowledge=knowledge)
    finally:
        game.close()
    return split_by_reply_shape(runs, tag_pains(runs, rooms), decisions)


def split_by_reply_shape(runs: list[Any], tags: list[Any], decisions: list[Any]) -> dict[str, int]:
    """Moves and mistakes in single-move replies, in the first move of a multi-move reply, and in
    the later moves of one."""
    out = dict.fromkeys(("single_moves", "single_mistakes", "first_moves", "first_mistakes",
                         "later_moves", "later_mistakes"), 0)  # fmt: skip
    seen: dict[int, int] = {}
    for run, found in zip(runs, tags, strict=True):
        position = seen.get(run.decision, 0)
        seen[run.decision] = position + 1
        multi = move_lines(decisions[run.decision].reply) > 1
        kind = "later" if multi and position > 0 else "first" if multi else "single"
        out[f"{kind}_moves"] += 1
        out[f"{kind}_mistakes"] += len(found)
    return out


def attribution(depth: int, args: argparse.Namespace) -> dict[str, int]:
    """Summed move and mistake counts by reply shape over the twelve games of one depth."""
    total: dict[str, int] = {}
    for case in card_sensitivity.sensitivity_cases():
        log = (
            args.root
            / f"depth-{depth}"
            / "episodes"
            / f"{NO_CARD.card_id}-{case.level}-s{case.seed}.jsonl"
        )
        for key, count in attribute_mistakes(log, case, args).items():
            total[key] = total.get(key, 0) + count
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depths", default="16,32,48")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(argv)
    rows: dict[str, Any] = {}
    for depth in (int(d) for d in args.depths.split(",")):
        rows[str(depth)] = depth_stats(play_depth(depth, args))
        rows[str(depth)]["by_reply_shape"] = attribution(depth, args)
        print(depth, json.dumps(rows[str(depth)]), flush=True)
    document = {
        "schema": SCHEMA,
        "label": "decision-depth check, Spark no card, 12 training cases [measured]",
        "depths": rows,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
