"""Exploratory ceiling check: how far can the model's decisions move the score on training maps?

Scripted policies (best specified and worst) play the same cases the model's no-card games
played, through the same engine player and fitness. Training maps only; no model call is made.
Writes counts and fitness numbers; the spread is also given in units of the model's own SD.

Usage: ceiling_check.py --wad WAD --root DIR --state STATE [--out FILE] [--workers N]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

import play_case
import script_paths

script_paths.add_script_dirs()

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.game_fitness import Case, Grade, fitness  # noqa: E402
from symbiont.act1.glimmer import Reply, ReplyFn  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.act1.policies import policy_named  # noqa: E402

NO_CARD = Card.of([])
# Hand-specified policies that ignore what the model would see: three lines is the longest reply.
FIXED = {
    "exit_x1": "go_to(exit)",
    "exit_x3": "go_to(exit)\ngo_to(exit)\ngo_to(exit)",
    "key_door_exit": "go_to(key)\nopen_door()\ngo_to(exit)",
}
SEEDED = ("random", "scripted_explorer", "stand_still", "fire_in_place", "spin")
BEST_CANDIDATES = tuple(FIXED)


class ScriptedReplies:
    """Picklable reply factory for one named policy (a spawned worker needs to rebuild it)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, _card: Card, case: Case) -> ReplyFn:
        if self.name in FIXED:
            text = FIXED[self.name]
            return lambda _prompt: Reply(text, "stop", 0)
        return policy_named(self.name, case.seed).reply


def model_cases_and_scores(state: Path) -> dict[Case, float]:
    """The graded no-card games in a state file as case to fitness."""
    games = json.loads(state.read_text())["games"]
    found = {}
    for key, game in games.items():
        if key.startswith(NO_CARD.card_id) and game["grade"] == Grade.GRADED.value:
            level, seed, skill, cuts = key.split("|")[1:]
            found[Case(level, int(seed), int(skill), CutSetting(cuts))] = game
    return {case: model_fitness(game) for case, game in found.items()}


def model_fitness(game: dict) -> float:
    """Fitness from a stored game record, with the same weights the loop uses."""
    from symbiont.act1.game_fitness import GameResult

    case = Case(
        game["case"]["level"],
        game["case"]["seed"],
        game["case"]["skill"],
        CutSetting(game["case"]["cuts"]),
    )
    return fitness(
        GameResult(
            case=case, card_id=game["card_id"], grade=Grade.GRADED,
            exit_reached=game["exit_reached"], route_share=game["route_share"],
            mistakes=game["mistakes"], died=game["died"], kills=game["kills"],
            cut_moves=game["cut_moves"], ungraded_reason=None,
        )
    )  # fmt: skip


def play_policy(name: str, cases: list[Case], args: argparse.Namespace) -> dict[Case, float]:
    """Fitness of one scripted policy on every case."""
    setup = play_case.EngineSetup(
        wad=args.wad, episodes=args.root / "ceiling" / name, workers=args.workers
    )
    setup.episodes.mkdir(parents=True, exist_ok=True)
    scores: dict[Case, float] = {}
    player = play_case.EnginePlayer(ScriptedReplies(name), setup)
    player.play_many(
        [(NO_CARD, case) for case in cases],
        lambda _card, case, result: scores.__setitem__(case, fitness(result)),
    )
    return scores


def summary(scores: dict[Case, float]) -> dict[str, float]:
    values = list(scores.values())
    return {
        "mean": round(statistics.fmean(values), 4),
        "sd": round(statistics.stdev(values), 4),
        "n": len(values),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    model = model_cases_and_scores(args.state)
    cases = sorted(model, key=lambda case: (case.level, case.seed))
    rows = {"muse_spark_no_card": summary(model)}
    for name in (*BEST_CANDIDATES, *SEEDED):
        rows[name] = summary(play_policy(name, cases, args))
        print(name, rows[name], flush=True)
    document = {
        "label": "ceiling check, training maps [measured]",
        "cases": len(cases),
        "rows": rows,
    }
    if args.out:
        args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(document, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
