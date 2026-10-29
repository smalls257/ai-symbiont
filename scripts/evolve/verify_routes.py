"""Route verifier: does a scripted explorer really reach the exit of a level in the engine?

A route that passes the smoke test but that no walker can follow is a level wasted on evolution.
This plays `go_to(exit)` on the real engine until the level ends and reports where it stopped.
The player holds every key, as the smoke test assumes; monsters are removed and the player is
invulnerable, since this checks the geometry and the switches, not combat.

Usage: verify_routes.py --wad data/freedoom/freedoom2.wad --out ~/symbiont-runs/evolve/routes.json
       [--levels MAP01 MAP02]
"""

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1 import goto  # noqa: E402 - path set above
from symbiont.act1.episode import MapKnowledge, RunLog, run_episode  # noqa: E402
from symbiont.act1.game_fitness import ALL_KEY_COLORS  # noqa: E402
from symbiont.act1.glimmer import Reply  # noqa: E402
from symbiont.act1.levels import LevelSplit, levels_in, require_training  # noqa: E402
from symbiont.act1.map_index import build_index  # noqa: E402
from symbiont.act1.navmap import build_navmap  # noqa: E402
from symbiont.act1.steplog import MoveRun  # noqa: E402
from symbiont.act1.wad import read_map  # noqa: E402

CYCLE = ("go_to(exit)", "turn(90)", "go_to(exit)")  # keys are given, so no key walk
MAX_DECISIONS = 24
STUCK_REPEATS = 6  # the same stop reason this many times in a row: the walk is not going on


@dataclass(frozen=True)
class RouteCheck:
    """How far a scripted walk got on one level."""

    level: str
    reached_exit: bool
    decisions: int
    last_outcomes: tuple[str, ...]


class _Unthreatened:
    """A game wrapper: after every new episode the monsters are gone and the player cannot die."""

    def __init__(self, game: Any) -> None:
        self._game = game

    def new_episode(self) -> None:
        self._game.new_episode()
        self._game.send_game_command("god")
        self._game.send_game_command("kill monsters")
        self._game.send_game_command("give keys")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._game, name)


class _KeysInHand:
    """The nav with every key color held: the player was given the keys, the tracker never saw."""

    def __init__(self, nav: Any) -> None:
        self._nav = nav

    def nearest_now(self, world: Any, from_xy: Any, candidates: Any, _keys_held: Any) -> Any:
        """Route as the smoke test does: every key is held."""
        return self._nav.nearest_now(world, from_xy, candidates, ALL_KEY_COLORS)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._nav, name)


def _cycling_reply() -> Callable[[str], Reply]:
    """A reply function that says the next move of CYCLE each time it is asked."""
    asked = 0

    def reply(_prompt: str) -> Reply:
        """The next move of the cycle."""
        nonlocal asked
        asked += 1
        return Reply(text=CYCLE[(asked - 1) % len(CYCLE)], finish_reason="stop", reasoning_chars=0)

    return reply


class StalledError(Exception):
    """The same cycle of moves has ended the same way twice: nothing will change."""


def _watch(outcomes: list[str]) -> Callable[[MoveRun], None]:
    """An on_move observer that records outcomes and raises StalledError on a repeated cycle."""

    def record(run: MoveRun) -> None:
        """Note the move's outcome; stop when the last cycle repeats the one before."""
        outcomes.append(f"{run.label} -> {run.outcome}")
        cycle = len(CYCLE)
        if len(outcomes) >= 2 * cycle and outcomes[-cycle:] == outcomes[-2 * cycle : -cycle]:
            raise StalledError

    return record


def verify_level(wad: Path, level: str) -> RouteCheck:
    """Play one level with the walking moves only; True when the level ended by its exit."""
    from symbiont.act1.engine import make_game

    require_training(level)  # no episode on a held-out level before the freeze (plan ruling 3)
    goto.ENEMY_IN_THE_WAY_UNITS = 0.0  # monsters are removed; a leftover must not stop the walk
    geometry = read_map(wad.read_bytes(), level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, _KeysInHand(build_navmap(geometry, index)))
    game = make_game(wad, level)
    outcomes: list[str] = []
    try:
        with contextlib.suppress(StalledError):  # the outcomes say where it stopped
            run_episode(
                _Unthreatened(game),
                _cycling_reply(),
                MAX_DECISIONS,
                RunLog(on_move=_watch(outcomes)),
                knowledge=knowledge,
            )
        ended = game.is_episode_finished() and not game.is_player_dead()
    finally:
        game.close()
    return RouteCheck(level, ended, len(outcomes), tuple(outcomes[-STUCK_REPEATS:]))


def main(argv: list[str] | None = None) -> int:
    """Verify the given levels (default: all 32) and write one JSON line per level."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--levels", nargs="*", default=list(levels_in(LevelSplit.TRAINING)))
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a") as out:
        for level in args.levels:
            check = verify_level(args.wad, level)
            out.write(json.dumps(asdict(check)) + "\n")
            out.flush()
            print(level, "EXIT" if check.reached_exit else "stopped", check.last_outcomes[-2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
