"""Quick exploratory check on training maps: situational lessons vs no lesson vs fixed cards.

Phases: `tune` picks the ranker cutoff on selection-level decisions, leaving each decision's own
level out; `play` runs one arm on the shared cases (validation maps plus fresh seeds on selection
maps); `report` pairs the arms by case and prints show rate. Training maps only.

Usage: lesson_check.py --phase tune|play|report --root DIR --lessons FILE [--arm A] [--wad W]
"""

import argparse
import json
import math
import statistics
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import frozen_cards  # noqa: E402 - needs the sibling path added above
import lesson_players  # noqa: E402
import paired_traces  # noqa: E402
import play_case  # noqa: E402
import run_evolve  # noqa: E402
import run_state  # noqa: E402
import spark_players  # noqa: E402

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.episode import load_run_log  # noqa: E402
from symbiont.act1.evolve_split import TRAINING_SKILLS, EvolveSplit  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.act1.situational import cutoff_for_show_rate  # noqa: E402
from symbiont.egress.spark import DEFAULT_MAX_TOKENS, Effort, SparkApiError, SparkReplyError  # noqa: E402

DECISIONS = 32
SHOW_RATE = 0.2  # the cutoff shows a lesson on about one decision in five of the training decisions
SEED_BASE = 950_001
RUN_CAP = 3.0
SEEDS_ON_VALIDATION, SEEDS_ON_SELECTION = 6, 2


class Arm(StrEnum):
    """The conditions compared; each plays in its own state file."""

    NONE = "none"
    MINED = "mined"
    ONE_MOVE = "one_move"
    LESSONS = "lessons"


def check_cases(split: EvolveSplit) -> list[Case]:
    """Validation maps x 6 seeds, selection maps x 2 fresh seeds, skills cycling; training only."""
    cases, seed = [], SEED_BASE
    for levels, count in (
        (split.validation, SEEDS_ON_VALIDATION),
        (split.selection, SEEDS_ON_SELECTION),
    ):
        for level in levels:
            for index in range(count):
                skill = TRAINING_SKILLS[(seed + index) % len(TRAINING_SKILLS)]
                cases.append(Case(level, seed, skill, CutSetting.NONE))
                seed += 1
    return cases


def arm_card(arm: Arm) -> Card:
    """The card an arm plays with; the lessons arm plays with none and adds lessons per decision."""
    return {Arm.MINED: frozen_cards.MINED_CARD, Arm.ONE_MOVE: paired_traces.ONE_MOVE}.get(
        arm, Card.of([])
    )


def tune(args: argparse.Namespace) -> None:
    """The cutoff for SHOW_RATE, from leave-case-out top scores on no-card selection decisions."""
    scores = []
    for log in sorted((args.root / "traces-32" / "episodes").glob("e3b0c44298fc-*.jsonl")):
        level = log.stem.split("-")[1]  # whole level left out: other seeds of it look identical
        ranker = lesson_players.ranker_from(str(args.lessons), f"{level}-")
        scores += [max(ranker.scores(d.observation)) for d in load_run_log(log)]
    # Rounded down: scores are floats, and an exact match must not miss by the last digit.
    cutoff = math.floor(cutoff_for_show_rate(scores, SHOW_RATE) * 1000) / 1000
    out = {"cutoff": cutoff, "show_rate_target": SHOW_RATE, "decisions": len(scores)}
    (args.root / "lessonchk-cutoff.json").write_text(json.dumps(out))
    print(out)


def play(args: argparse.Namespace) -> None:
    """One arm on every check case; resumable."""
    run = f"lessonchk-{args.arm}"
    store = run_state.RunStore(args.root / run)
    store.require_identity(
        {
            "player": "spark",
            "author": "none",
            "model": spark_players.MODEL,
            "reasoning": f"low; {DECISIONS} decisions; arm {args.arm}",
        }  # fmt: skip
    )
    if args.arm == Arm.LESSONS:
        cutoff = json.loads((args.root / "lessonchk-cutoff.json").read_text())["cutoff"]
        replies: Any = lesson_players.LessonPlayers(
            run, RUN_CAP, str(args.lessons), cutoff, str(args.root / run / "shows.jsonl")
        )
    else:
        replies = spark_players.SparkPlayers(
            run=run, run_cap=RUN_CAP, effort=Effort.LOW, max_tokens=DEFAULT_MAX_TOKENS
        )
    setup = play_case.EngineSetup(
        wad=args.wad, episodes=args.root / run / "episodes", decisions=DECISIONS,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
    )  # fmt: skip
    split = EvolveSplit.of(run_evolve.read_smoke(args.levels))
    player = run_state.ResumingPlayer(play_case.EnginePlayer(replies, setup), store)
    done: list[GameResult] = []
    card = arm_card(args.arm)
    player.play_many(
        [(card, case) for case in check_cases(split)],
        lambda _card, _case, result: done.append(result),
    )
    print(f"{args.arm}: {len(done)} games", flush=True)


def arm_scores(root: Path, arm: Arm) -> dict[str, tuple[float, bool]]:
    """Fitness and exit by case name for the graded games of one arm."""
    games = json.loads((root / f"lessonchk-{arm}" / "state.json").read_text())["games"]
    found = {}
    for key, game in games.items():
        if game["grade"] != Grade.GRADED.value:
            continue
        played = game["case"]
        result = GameResult(
            case=Case(played["level"], played["seed"], played["skill"], CutSetting(played["cuts"])),
            card_id=game["card_id"], grade=Grade.GRADED, exit_reached=game["exit_reached"],
            route_share=game["route_share"], mistakes=game["mistakes"], died=game["died"],
            kills=game["kills"], cut_moves=game["cut_moves"], ungraded_reason=None,
        )  # fmt: skip
        found[key.split("|", 1)[1]] = (fitness(result), result.exit_reached)
    return found


def show_rate(root: Path) -> dict[str, float]:
    """Share of decisions that showed any lesson, and the mean number shown when one did."""
    lines = [
        json.loads(x) for x in (root / "lessonchk-lessons" / "shows.jsonl").read_text().splitlines()
    ]
    shown = [x["shown"] for x in lines if x["shown"]]
    return {
        "decisions": len(lines),
        "show_rate": round(len(shown) / len(lines), 3),
        "mean_shown_when_shown": round(statistics.fmean(shown), 2) if shown else 0.0,
    }


def report(args: argparse.Namespace) -> None:
    """Paired comparison of every arm against no lesson, by case."""
    scores = {arm: arm_scores(args.root, arm) for arm in Arm}
    shared = set.intersection(*(set(s) for s in scores.values()))
    rows: dict[str, Any] = {}
    for arm in Arm:
        diffs = [scores[arm][c][0] - scores[Arm.NONE][c][0] for c in shared]
        rows[arm.value] = {
            "cases": len(shared),
            "fitness": round(statistics.fmean(scores[arm][c][0] for c in shared), 3),
            "exits": sum(scores[arm][c][1] for c in shared),
            "vs_none": round(statistics.fmean(diffs), 3),
            "vs_none_se": round(statistics.stdev(diffs) / len(diffs) ** 0.5, 3)
            if arm != Arm.NONE
            else 0.0,
        }
    document = {"label": "lessons check, training maps, exploratory [measured]", "arms": rows,
                "lesson_shows": show_rate(args.root)}  # fmt: skip
    (args.root / "lessonchk-report.json").write_text(json.dumps(document, indent=1))
    print(json.dumps(document, indent=1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("tune", "play", "report"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lessons", type=Path, required=True)
    parser.add_argument("--arm", type=Arm, choices=list(Arm))
    parser.add_argument("--wad", type=Path)
    parser.add_argument("--levels", type=Path, default=Path("results/evolve-levels.json"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    {"tune": tune, "play": play, "report": report}[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
