"""Run Evolve: resumable, with per-game timing events, and never scored without a frozen prereg.

A Spark run past generation 0 needs --prereg (frozen) or --exploratory, which labels the run
exploratory. A dry run needs --dry-run and says SIMULATED. Held-out levels are never played here.

Usage: run_evolve.py --run NAME --player fake|scripted|spark --author fake|spark --generations N
"""

import argparse
import json
import sys
from enum import StrEnum
from pathlib import Path

import script_paths

script_paths.add_script_dirs()

import fake_author  # noqa: E402 - needs the sibling path added above
import fake_player  # noqa: E402
import seed_cards  # noqa: E402
import spark_players  # noqa: E402
from run_state import (  # noqa: E402
    NullLedger,
    PlayerChangedError,
    ResumingPlayer,
    RunLedger,
    RunStore,
    game_key,
    result_from_json,
    result_to_json,
)

from symbiont.act1.evolution import Player, RunRecord, RunRules, evolve  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit, SmokeResult  # noqa: E402
from symbiont.act1.generation import OperatorSchedule, VariationTools  # noqa: E402
from symbiont.act1.levels import LevelSplit, levels_in  # noqa: E402
from symbiont.act1.lineage import Arm  # noqa: E402
from symbiont.act1.run_guards import SpendRoom  # noqa: E402
from symbiont.act1.run_summary import summary_of  # noqa: E402
from symbiont.egress.spark import Effort, SparkApiError, SparkReplyError  # noqa: E402
from symbiont.eval.prereg import PreregNotFrozenError  # noqa: E402
from symbiont.eval.prereg_git import require_frozen  # noqa: E402

__all__ = ["PlayerChangedError", "game_key", "result_from_json", "result_to_json"]

DEFAULT_ROOT = Path.home() / "symbiont-runs" / "evolve"
# The dry run spends nothing; the room only has to be large enough that doubling fits.
DRY_RUN_ROOM = SpendRoom(5.0, 2.5)
# Planning figure [hypothesis]: playing generation 0 a second time over costs about this much.
SPARK_DOUBLING_COST = 0.3
PLAY_EFFORT = Effort.LOW  # the probe ruling: play at low reasoning
MUTATION_EFFORT = Effort.MEDIUM  # mutation and judge
PLAY_DECISIONS = 16
SIMULATED_BANNER = (
    "SIMULATED: a dry run; no real game was played and none of these numbers is a result"
)
EXPLORATORY_NOTE = "validation = held-back seeds (weaker than validation levels)"


class PlayerKind(StrEnum):
    """Who plays the games."""

    FAKE = "fake"
    SCRIPTED = "scripted"
    SPARK = "spark"


class AuthorKind(StrEnum):
    """Who writes the children."""

    FAKE = "fake"
    SPARK = "spark"


class RunLabel(StrEnum):
    """What a run is allowed to claim. There is no SCORED here: scored runs are the final test."""

    DRY_RUN = "dry run"
    EXPLORATORY = "exploratory"


class FakePlayerNeedsDryRunError(RuntimeError):
    """The fake player was asked for without --dry-run: its scores are simulated, never a result."""


class UnlabeledRunError(RuntimeError):
    """Neither --dry-run nor --exploratory (nor a frozen prereg for Spark) was given."""


def label_of(args: argparse.Namespace) -> RunLabel | None:
    """The run's label from its flags; None means a scored-style run that needs a frozen prereg."""
    if args.dry_run and args.exploratory:
        raise UnlabeledRunError("--dry-run and --exploratory exclude each other")
    if args.dry_run:
        return RunLabel.DRY_RUN
    return RunLabel.EXPLORATORY if args.exploratory else None


def require_scored_ready(
    player: PlayerKind, generations: int, prereg: Path | None, label: RunLabel | None
) -> None:
    """Refuse a Spark run past generation 0 unless it is exploratory or the prereg is frozen.

    Raises PreregNotFrozenError (from symbiont.eval.prereg).
    """
    if player != PlayerKind.SPARK or generations < 1 or label == RunLabel.EXPLORATORY:
        return
    if prereg is None:
        raise PreregNotFrozenError("--prereg", "generation 1 or later with --player spark")
    require_frozen(prereg)


def read_smoke(path: Path) -> dict[str, SmokeResult]:
    """Smoke results from the local file (reasons) or the published one (pass or drop labels)."""
    raw = json.loads(path.read_text())
    if "levels" in raw:
        return {
            level: SmokeResult(passed=label == "pass", reason="" if label == "pass" else label)
            for level, label in raw["levels"].items()
        }
    return {level: SmokeResult(**result) for level, result in raw.items()}


def split_for(args: argparse.Namespace) -> EvolveSplit:
    """The exploratory split for --pool, else the split from a smoke-test file, else all pass."""
    if args.pool:
        return EvolveSplit.exploratory(args.pool.split(","))
    every = levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT)
    if args.levels is None:
        return EvolveSplit.of({level: SmokeResult(passed=True, reason="") for level in every})
    return EvolveSplit.of(read_smoke(args.levels))


def build_player(args: argparse.Namespace, episodes: Path) -> Player:
    """The player for the run."""
    if args.player == PlayerKind.FAKE:
        return fake_player.HiddenRulePlayer()
    import play_case

    if args.player == PlayerKind.SPARK:
        replies = spark_players.SparkPlayers(args.run, args.run_cap, PLAY_EFFORT)
    else:
        replies = spark_players.ScriptedPlayers("scripted_explorer")
    setup = play_case.EngineSetup(
        wad=args.wad,
        episodes=episodes,
        decisions=PLAY_DECISIONS,
        ungradable=(play_case.GlimmerReplyError, SparkReplyError, SparkApiError),
        workers=args.workers,
    )
    return play_case.EnginePlayer(replies, setup)


def build_tools(args: argparse.Namespace) -> VariationTools:
    """Author, judge, chance and schedule for one arm; Spark ones get their own session."""
    schedule = OperatorSchedule(args.seed)
    if args.author == AuthorKind.FAKE:
        return VariationTools(
            fake_author.OfflineAuthor(), fake_author.AllowAllJudge(), schedule, {}, args.seed
        )
    import spark_author
    import spark_judge

    session = spark_players.RetryingSession(spark_players.spark_session(args.run, args.run_cap))
    return VariationTools(
        spark_author.SparkAuthor(session, MUTATION_EFFORT),
        spark_judge.SparkJudge(session, MUTATION_EFFORT),
        schedule, {}, args.seed,
    )  # fmt: skip


def spark_in_use(args: argparse.Namespace) -> bool:
    """Whether this run makes paid calls."""
    return args.player == PlayerKind.SPARK or args.author == AuthorKind.SPARK


def spend_room_for(args: argparse.Namespace) -> SpendRoom:
    """The money left for the noise check's doubling decision."""
    if not spark_in_use(args):
        return DRY_RUN_ROOM
    spent = RunLedger(args.run).snapshot()["dollars"]
    return SpendRoom(args.run_cap - spent, SPARK_DOUBLING_COST)


def seed_population(args: argparse.Namespace, tools: VariationTools) -> list:
    """The generation-0 cards: Spark-written when the author is Spark, offline otherwise."""
    if args.author == AuthorKind.FAKE:
        return fake_author.dry_run_seed_cards()
    return seed_cards.build_seed_cards(tools.author, tools.judge)


def label_text(args: argparse.Namespace, label: RunLabel | None) -> str:
    """The words the page and the results show for this run."""
    base = f"{args.player.value} player"
    if label == RunLabel.DRY_RUN:
        return f"dry run, {base}"
    if not args.pool:
        return f"exploratory, {base}"
    maps = len(args.pool.split(","))
    return f"exploratory, {base}, {maps} training maps; {EXPLORATORY_NOTE}"


def run(args: argparse.Namespace) -> RunRecord:
    """One run: guards first, then the loop under the resuming player."""
    label = label_of(args)
    if args.player == PlayerKind.FAKE and label != RunLabel.DRY_RUN:
        raise FakePlayerNeedsDryRunError("--player fake scores a hidden rule: pass --dry-run")
    require_scored_ready(args.player, args.generations, args.prereg, label)
    if label is None:
        raise UnlabeledRunError("pass --dry-run or --exploratory; scored runs are the final test")
    store = RunStore(args.root / args.run)
    store.require_identity(
        {
            "player": args.player.value,
            "author": args.author.value,
            "model": args.model or (spark_players.MODEL if spark_in_use(args) else None),
            "reasoning": args.reasoning or (PLAY_EFFORT.value if spark_in_use(args) else None),
        }
    )
    store.event("start", player=args.player.value, author=args.author.value, label=label.value)
    player = ResumingPlayer(build_player(args, args.root / args.run / "episodes"), store)
    tools = {arm: build_tools(args) for arm in (Arm.EVOLVED, Arm.NO_SELECTION)}
    rules = RunRules(args.generations, args.seed, 1, spend_room_for(args), journal=store)
    record = evolve(
        store.seeds(lambda: seed_population(args, tools[Arm.EVOLVED])), split_for(args),
        player, tools, rules,
    )  # fmt: skip
    ledger = RunLedger(args.run) if spark_in_use(args) else NullLedger()
    summary = summary_of(record, label_text(args, label), "exploratory", ledger.snapshot())
    summary["games_replayed_from_state"] = player.replayed
    (store.directory / "summary.json").write_text(json.dumps(summary, indent=1))
    store.event("end", stop_reason=record.stop_reason, replayed=player.replayed)
    return record


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Command line; the player and author are enums, never free strings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--player", type=PlayerKind, choices=list(PlayerKind), required=True)
    parser.add_argument(
        "--author", type=AuthorKind, choices=list(AuthorKind), default=AuthorKind.FAKE
    )
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--pool", help="comma-separated training maps for the exploratory split")
    parser.add_argument("--levels", type=Path)
    parser.add_argument("--prereg", type=Path)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--wad", type=Path, default=Path("data") / "freedoom" / "freedoom2.wad")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--run-cap", type=float, default=3.0, help="dollars for this run")
    parser.add_argument("--model", help="the player's model, recorded with every game")
    parser.add_argument("--reasoning", help="the player's reasoning effort, recorded too")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exploratory", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run and print one line per generation: means, gap, guards."""
    args = parse_arguments(argv)
    if args.dry_run:
        print(SIMULATED_BANNER)
    record = run(args)
    for arm, tables in record.tables.items():
        for generation, table in enumerate(tables):
            means = [
                sum(table.scores[(c, k)] for k in table.cases) / len(table.cases)
                for c in table.cards
            ]
            mean = sum(means) / len(means)
            print(f"{arm.value} gen {generation}: mean {mean:.3f} best {max(means):.3f}")
    for generation, training, validation in record.gaps:
        print(f"gap gen {generation}: {training - validation:+.3f}")
    verdict = record.noise.verdict.value if record.noise else "none"
    print(f"noise: {verdict}; stop: {record.stop_reason}")
    if args.dry_run:
        print(SIMULATED_BANNER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
