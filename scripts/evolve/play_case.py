"""The engine player: one card on one case becomes one GameResult (periphery: ViZDoom, files).

A Spark or Glimmer error during a move makes the game ungraded with the error class as its
reason. A privacy refusal or a spend cap is not in `ungradable`, so it propagates and stops the
run: neither may be read as a lost game.
"""

import collections
import concurrent.futures
import multiprocessing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

import collect_episodes  # noqa: E402 - needs the sibling path added above

from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.card_prompt import with_card  # noqa: E402
from symbiont.act1.episode import MapKnowledge, RunLog, run_episode  # noqa: E402
from symbiont.act1.episode_records import EpisodeEnd  # noqa: E402
from symbiont.act1.game_fitness import (  # noqa: E402
    Case,
    GameResult,
    Grade,
    NoRouteError,
    remaining_route_units,
    route_share,
)
from symbiont.act1.game_pains import tag_pains  # noqa: E402
from symbiont.act1.glimmer import GlimmerReplyError, ReplyFn  # noqa: E402
from symbiont.act1.levels import require_training  # noqa: E402
from symbiont.act1.move_cuts import cuts_for  # noqa: E402
from symbiont.act1.navmap import NavMap  # noqa: E402
from symbiont.act1.rooms import RoomFinder  # noqa: E402
from symbiont.act1.steplog import MoveRun  # noqa: E402
from symbiont.eval.prereg import FrozenPrereg, PreregNotFrozenError  # noqa: E402

CUT_PREFIX = "cut short after"
REASON_CHARS = 160  # the error class and the start of its message: why a game is ungraded
Loaded = tuple[Any, MapKnowledge, RoomFinder]


def load_case_level(wad: Path, case: Case) -> Loaded:
    """Seam: the only function that touches ViZDoom or the WAD for Evolve."""
    from symbiont.act1.engine import Start, make_game
    from symbiont.act1.map_index import build_index
    from symbiont.act1.navmap import build_navmap
    from symbiont.act1.wad import read_map

    geometry = read_map(wad.read_bytes(), case.level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    return make_game(wad, case.level, Start(case.seed, case.skill)), knowledge, RoomFinder(geometry)


def spawn_pool(workers: int) -> concurrent.futures.Executor:
    """A process pool of fresh interpreters: one ViZDoom engine each."""
    return concurrent.futures.ProcessPoolExecutor(
        workers, mp_context=multiprocessing.get_context("spawn")
    )


def kill_count(game: Any) -> int:
    """Monsters the player killed, read from the engine's own counter."""
    import vizdoom as vzd

    return int(game.get_game_variable(vzd.GameVariable.KILLCOUNT))


class RunMode(StrEnum):
    """What the games are for. Only FINAL_TEST may touch a held-out level."""

    TRAINING = "training"
    FINAL_TEST = "final_test"


class NotInFinalTestError(ValueError):
    """A level outside the frozen prereg's held-out list was asked for in a final test."""


class MissingMapError(RuntimeError):
    """A level loaded without map data: route share cannot be measured, so it is not graded."""


@dataclass(frozen=True)
class EngineSetup:
    """Where the WAD and decision logs live, and which errors mark a game ungraded."""

    wad: Path
    episodes: Path
    decisions: int = 16
    ungradable: tuple[type[Exception], ...] = (GlimmerReplyError,)
    mode: RunMode = RunMode.TRAINING
    # FINAL_TEST only: the prereg and the held-out levels it names. A frozen prereg alone opens
    # nothing; training mode ignores both.
    frozen_prereg: FrozenPrereg | None = None
    final_levels: frozenset[str] = frozenset()
    loader: Callable[[Path, Case], Loaded] = field(default=load_case_level)
    kills: Callable[[Any], int] = field(default=kill_count)
    workers: int = 1
    # Spawned processes: one ViZDoom engine per process, and a fresh interpreter, not a fork.
    executor_factory: Callable[[int], concurrent.futures.Executor] = field(default=spawn_pool)


def _play_one(player: "EnginePlayer", card: Card, case: Case) -> GameResult:
    """A pool job: one game. Top level, so a process pool can pickle it."""
    return player.play(card, case)


def _pain_counts(runs: list[MoveRun], rooms: RoomFinder) -> tuple[tuple[str, int], ...]:
    """Tagger counts by tag name, in tag order."""
    counts = collections.Counter(str(tag) for tags in tag_pains(runs, rooms) for tag in tags)
    return tuple(sorted(counts.items()))


class EnginePlayer:
    """Implements the loop's Player protocol over ViZDoom."""

    def __init__(self, reply_for: Callable[[Card, Case], ReplyFn], setup: EngineSetup) -> None:
        """`reply_for` gives the model's reply function for a card and case."""
        self.reply_for, self.setup = reply_for, setup

    def play(self, card: Card, case: Case) -> GameResult:
        """Play one game. Raises HeldOutLevelError before any engine call for a held-out level."""
        self._require_allowed(case.level)
        loaded = self.setup.loader(self.setup.wad, case)
        try:
            return self._play_loaded(card, case, loaded)
        finally:
            loaded[0].close()

    def play_many(
        self,
        pairs: Sequence[tuple[Card, Case]],
        on_result: Callable[[Card, Case, GameResult], None],
    ) -> None:
        """Play the pairs on `workers` processes; `on_result` hears each game as it finishes.

        Any error ends the batch: queued games are canceled and the error propagates (a spend
        cap or a privacy refusal stops the run, never a fake result).
        """
        if self.setup.workers <= 1:
            for card, case in pairs:
                on_result(card, case, self.play(card, case))
            return
        with self.setup.executor_factory(self.setup.workers) as pool:
            jobs = {pool.submit(_play_one, self, card, case): (card, case) for card, case in pairs}
            try:
                for job in concurrent.futures.as_completed(jobs):
                    on_result(*jobs[job], job.result())
            except BaseException:
                pool.shutdown(wait=True, cancel_futures=True)
                raise

    def _require_allowed(self, level: str) -> None:
        """Training mode plays training levels only; the final test plays its frozen list only."""
        setup = self.setup
        if setup.mode == RunMode.TRAINING:
            require_training(level)
            return
        if setup.frozen_prereg is None:
            raise PreregNotFrozenError("final test", "no frozen prereg was given")
        if level not in setup.final_levels:
            raise NotInFinalTestError(f"{level} is not in the final test's list")

    def _play_loaded(self, card: Card, case: Case, loaded: Loaded) -> GameResult:
        """Run the episode on a loaded level and grade it, or mark it ungraded."""
        game, knowledge, rooms = loaded
        nav = knowledge.nav
        if nav is None:
            raise MissingMapError(f"{case.level} has no map data: refusing to grade it")
        game.new_episode()
        start = tuple(game.get_state().game_variables[2:4])
        start_units = remaining_route_units(nav, start)
        runs: list[MoveRun] = []
        reply = with_card(self.reply_for(card, case), card)
        log = self.setup.episodes / f"{card.card_id}-{case.level}-s{case.seed}.jsonl"
        run_log = RunLog(log, {"card": card.card_id}, runs.append, cuts_for(case.cuts, case.seed))
        try:
            run_episode(game, reply, self.setup.decisions, run_log, knowledge=knowledge)
        except self.setup.ungradable as error:
            return self._ungraded(
                card, case, f"{type(error).__name__}: {str(error)[:REASON_CHARS]}"
            )
        ended = collect_episodes.how_it_ended(game)
        share = self._share(nav, runs, start_units, ended)
        pains = _pain_counts(runs, rooms)
        return GameResult(
            case=case,
            card_id=card.card_id,
            grade=Grade.GRADED,
            exit_reached=ended == EpisodeEnd.EXITED,
            route_share=share,
            mistakes=sum(count for _, count in pains),
            died=ended == EpisodeEnd.DIED,
            kills=self.setup.kills(game),
            cut_moves=sum(run.outcome.startswith(CUT_PREFIX) for run in runs),
            ungraded_reason=None,
            pains=pains,
        )

    @staticmethod
    def _share(nav: NavMap, runs: list[MoveRun], start_units: float, ended: EpisodeEnd) -> float:
        """The furthest route share reached on any spot the nav can route from (1 at an exit)."""
        # A lift or teleport can carry the player off the walkable grid: skipping that spot keeps
        # the progress made before it, and furthest rather than last means wandering back is free.
        if ended == EpisodeEnd.EXITED:
            return 1.0
        spots = {run.before.position for run in runs}
        if runs and runs[-1].after is not None:
            spots.add(runs[-1].after.position)
        best = 0.0
        for spot in sorted(spots):
            try:
                best = max(best, route_share(start_units, remaining_route_units(nav, spot)))
            except NoRouteError:
                continue
        return best

    @staticmethod
    def _ungraded(card: Card, case: Case, reason: str) -> GameResult:
        """A game that ended in a model error: ungraded, with the error class as the reason."""
        return GameResult(
            case=case,
            card_id=card.card_id,
            grade=Grade.UNGRADED,
            exit_reached=False,
            route_share=0.0,
            mistakes=0,
            died=False,
            kills=0,
            cut_moves=0,
            ungraded_reason=reason,
        )
