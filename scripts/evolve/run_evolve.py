"""Run Evolve: resumable, with per-game timing events, and never past generation 0 unfrozen.

`--player fake` plays a hidden rule with no engine (the dry run); `--player scripted` plays the
scripted explorer on the real engine; `--player spark` is refused for generation 1 and later
unless `--prereg` names a frozen, committed prereg. Held-out levels are never played here: the
final test is its own command. State lives outside the repo, mode 0600, written per game.

Usage: run_evolve.py --run NAME --player fake|scripted|spark --author fake|spark
       --generations N [--levels LEVELS_JSON] [--prereg PATH] [--root DIR] [--dry-run]
"""

import argparse
import dataclasses
import json
import os
import sys
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import fake_author  # noqa: E402 - needs the sibling path added above
import fake_player  # noqa: E402

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolution import Player, RunRecord, RunRules, evolve  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit, SmokeResult  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.generation import OperatorSchedule, VariationTools  # noqa: E402
from symbiont.act1.levels import LevelSplit, levels_in  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.act1.run_guards import SpendRoom  # noqa: E402
from symbiont.act1.run_summary import summary_of  # noqa: E402
from symbiont.eval.prereg_git import require_frozen  # noqa: E402

DEFAULT_ROOT = Path.home() / "symbiont-runs" / "evolve"
# The dry run spends nothing; the room only has to be large enough that doubling fits.
DRY_RUN_ROOM = SpendRoom(5.0, 2.5)


class PlayerKind(StrEnum):
    """Who plays the games."""

    FAKE = "fake"
    SCRIPTED = "scripted"
    SPARK = "spark"


class AuthorKind(StrEnum):
    """Who writes the children."""

    FAKE = "fake"
    SPARK = "spark"


class SparkNotBuiltError(RuntimeError):
    """The Spark player and author arrive with the Spark tasks (T19 on)."""


def game_key(card_id: str, case: Case) -> str:
    """The stable key of one game in the state file."""
    return f"{card_id}|{case.level}|{case.seed}|{case.skill}|{case.cuts.value}"


def result_to_json(result: GameResult) -> dict[str, Any]:
    """A game result as plain JSON."""
    out = dataclasses.asdict(result)
    out["grade"] = result.grade.value
    out["case"]["cuts"] = result.case.cuts.value
    out["pains"] = [list(pair) for pair in result.pains]
    return out


def result_from_json(data: dict[str, Any]) -> GameResult:
    """The inverse of result_to_json."""
    case = Case(**{**data["case"], "cuts": CutSetting(data["case"]["cuts"])})
    fields = {**data, "case": case, "grade": Grade(data["grade"])}
    fields["pains"] = tuple((name, count) for name, count in data["pains"])
    return GameResult(**fields)


class RunStore:
    """state.json (mode 0600, atomic per game) and events.jsonl for one run."""

    def __init__(self, directory: Path) -> None:
        """Create the run directory and read any earlier games."""
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path, self.events_path = directory / "state.json", directory / "events.jsonl"
        stored = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.games: dict[str, dict[str, Any]] = stored.get("games", {})
        self.cards: dict[str, str] = stored.get("cards", {})

    def save_game(self, key: str, result: GameResult, card: Card) -> None:
        """Record one game and the card's text, replacing state.json atomically."""
        self.games[key] = result_to_json(result)
        self.cards[card.card_id] = card.render()
        fd, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w") as handle:
            json.dump({"games": self.games, "cards": self.cards}, handle)
        Path(name).chmod(0o600)
        Path(name).replace(self.state_path)

    def event(self, name: str, **fields: Any) -> None:
        """Append one timing or stage event."""
        line = json.dumps({"event": name, "at": time.time(), **fields})
        with self.events_path.open("a") as handle:
            handle.write(line + "\n")


class ResumingPlayer:
    """Returns a stored game instead of replaying it, and stores every new one before returning."""

    def __init__(self, inner: Player, store: RunStore) -> None:
        """Wrap a player; `replayed` counts games served from the state file."""
        self.inner, self.store, self.replayed = inner, store, 0

    def play(self, card: Card, case: Case) -> GameResult:
        """One game, from the state file if it was already played."""
        key = game_key(card.card_id, case)
        if key in self.store.games:
            self.replayed += 1
            return result_from_json(self.store.games[key])
        started = time.monotonic()
        result = self.inner.play(card, case)
        self.store.save_game(key, result, card)
        self.store.event(
            "game", card=card.card_id, level=case.level, seed=case.seed,
            grade=result.grade.value, seconds=round(time.monotonic() - started, 3),
        )  # fmt: skip
        return result


def require_scored_ready(player: PlayerKind, generations: int, prereg: Path | None) -> None:
    """Refuse a Spark run past generation 0 unless the prereg is frozen and committed.

    Raises PreregNotFrozenError (from symbiont.eval.prereg).
    """
    if player == PlayerKind.SPARK and generations >= 1:
        if prereg is None:
            from symbiont.eval.prereg import PreregNotFrozenError

            raise PreregNotFrozenError("--prereg", "generation 1 or later with --player spark")
        require_frozen(prereg)


def split_from_levels(levels_json: Path | None) -> EvolveSplit:
    """The split from a smoke-test file; with none, every level passes (the dry run)."""
    every = levels_in(LevelSplit.TRAINING) + levels_in(LevelSplit.HELD_OUT)
    if levels_json is None:
        return EvolveSplit.of({level: SmokeResult(passed=True, reason="") for level in every})
    raw = json.loads(levels_json.read_text())
    return EvolveSplit.of({k: SmokeResult(**v) for k, v in raw.items()})


def build_player(kind: PlayerKind, wad: Path, episodes: Path) -> Player:
    """The player for the run. Spark waits for T19."""
    if kind == PlayerKind.FAKE:
        return fake_player.HiddenRulePlayer()
    if kind == PlayerKind.SPARK:
        raise SparkNotBuiltError("the Spark player arrives with T19")
    import play_case

    from symbiont.act1.policies import policy_named

    setup = play_case.EngineSetup(wad=wad, episodes=episodes)
    return play_case.EnginePlayer(
        lambda _card, case: policy_named("scripted_explorer", case.seed).reply, setup
    )


def build_tools(author: AuthorKind, seed: int) -> VariationTools:
    """Author, judge, chance and schedule for the run. Spark waits for T19."""
    if author == AuthorKind.SPARK:
        raise SparkNotBuiltError("the Spark author arrives with T19")
    import random

    return VariationTools(
        fake_author.OfflineAuthor(), fake_author.AllowAllJudge(), random.Random(seed),
        OperatorSchedule(seed), {},
    )  # fmt: skip


def run(args: argparse.Namespace) -> RunRecord:
    """One run: guards first, then the loop under the resuming player."""
    require_scored_ready(args.player, args.generations, args.prereg)
    store = RunStore(args.root / args.run)
    store.event(
        "start", player=args.player.value, author=args.author.value, generations=args.generations
    )
    player = ResumingPlayer(
        build_player(args.player, args.wad, args.root / args.run / "episodes"), store
    )
    rules = RunRules(args.generations, args.seed, 1, DRY_RUN_ROOM)
    record = evolve(
        fake_author.dry_run_seed_cards(), split_from_levels(args.levels), player,
        build_tools(args.author, args.seed), rules,
    )  # fmt: skip
    label = (
        f"dry run, {args.player.value} player"
        if args.dry_run
        else f"exploratory, {args.player.value} player"
    )
    summary = summary_of(record, label, "exploratory")
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
    parser.add_argument("--levels", type=Path)
    parser.add_argument("--prereg", type=Path)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--wad", type=Path, default=Path("data") / "freedoom" / "freedoom2.wad")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run and print one line per generation: means, gap, guards."""
    record = run(parse_arguments(argv))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
