"""The engine player: one card on one case becomes one GameResult (periphery: ViZDoom, files).

A Spark or Glimmer error during a move makes the game ungraded with the error class as its
reason. A privacy refusal or a spend cap is not in `ungradable`, so it propagates and stops the
run: neither may be read as a lost game.
"""

import collections
from collections.abc import Callable
from dataclasses import dataclass, field
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
    remaining_route_units,
    route_share,
)
from symbiont.act1.game_pains import tag_pains  # noqa: E402
from symbiont.act1.glimmer import GlimmerReplyError, ReplyFn  # noqa: E402
from symbiont.act1.levels import require_training  # noqa: E402
from symbiont.act1.move_cuts import cuts_for  # noqa: E402
from symbiont.act1.rooms import RoomFinder  # noqa: E402
from symbiont.act1.steplog import MoveRun  # noqa: E402
from symbiont.eval.prereg import FrozenPrereg  # noqa: E402

CUT_PREFIX = "cut short after"
Loaded = tuple[Any, MapKnowledge, RoomFinder]


def load_case_level(wad: Path, case: Case) -> Loaded:
    """Seam: the only function that touches ViZDoom or the WAD for Evolve."""
    from symbiont.act1.engine import make_game
    from symbiont.act1.map_index import build_index
    from symbiont.act1.navmap import build_navmap
    from symbiont.act1.wad import read_map

    geometry = read_map(wad.read_bytes(), case.level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    return make_game(wad, case.level, case.seed, skill=case.skill), knowledge, RoomFinder(geometry)


def kill_count(game: Any) -> int:
    """Monsters the player killed, read from the engine's own counter."""
    import vizdoom as vzd

    return int(game.get_game_variable(vzd.GameVariable.KILLCOUNT))


@dataclass(frozen=True)
class EngineSetup:
    """Where the WAD and decision logs live, and which errors mark a game ungraded."""

    wad: Path
    episodes: Path
    decisions: int = 16
    ungradable: tuple[type[Exception], ...] = (GlimmerReplyError,)
    frozen_prereg: FrozenPrereg | None = None
    loader: Callable[[Path, Case], Loaded] = field(default=load_case_level)
    kills: Callable[[Any], int] = field(default=kill_count)


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
        if self.setup.frozen_prereg is None:
            require_training(case.level)
        loaded = self.setup.loader(self.setup.wad, case)
        try:
            return self._play_loaded(card, case, loaded)
        finally:
            loaded[0].close()

    def _play_loaded(self, card: Card, case: Case, loaded: Loaded) -> GameResult:
        """Run the episode on a loaded level and grade it, or mark it ungraded."""
        game, knowledge, rooms = loaded
        nav = knowledge.nav
        game.new_episode()
        start = tuple(game.get_state().game_variables[2:4])
        start_units = remaining_route_units(nav, start) if nav else 0.0
        runs: list[MoveRun] = []
        reply = with_card(self.reply_for(card, case), card)
        log = self.setup.episodes / f"{card.card_id}-{case.level}-s{case.seed}.jsonl"
        run_log = RunLog(log, {"card": card.card_id}, runs.append, cuts_for(case.cuts, case.seed))
        try:
            run_episode(game, reply, self.setup.decisions, run_log, knowledge=knowledge)
        except self.setup.ungradable as error:
            return self._ungraded(card, case, type(error).__name__)
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
    def _share(nav: Any, runs: list[MoveRun], start_units: float, ended: EpisodeEnd) -> float:
        """Route share from where the player stood last; 1 at an exit, 0 with no move played."""
        if ended == EpisodeEnd.EXITED:
            return 1.0
        if not runs or nav is None:
            return 0.0
        last = runs[-1].after or runs[-1].before
        return route_share(start_units, remaining_route_units(nav, last.position))

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
