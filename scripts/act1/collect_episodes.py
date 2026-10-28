"""Collect scripted and random self-play episodes on training levels into gitignored data/.

Prevents Silent Fallback in the episode log: a held-out level, an existing episode file, an
episode with no moves and a failing level each stop the run with an error that names the level or
the session, so a bulk run never leaves a quietly short or overwritten log. Prevents Infected Core:
`load_level` is the only function that touches ViZDoom or the WAD, so the rest runs without them.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from symbiont.act1.episode import MapKnowledge, RunLog, run_episode
from symbiont.act1.episode_records import Episode, episode_records
from symbiont.act1.levels import LevelSplit, levels_in, require_training
from symbiont.act1.map_index import build_index
from symbiont.act1.navmap import build_navmap
from symbiont.act1.policies import policy_named
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveRun
from symbiont.act1.wad import read_map
from symbiont.records.schema import dump_jsonl

DEFAULT_POLICIES = "random,scripted_explorer"
DEFAULT_OUT = "data/act1/episodes"
FREEDOOM_DIR = Path("data") / "freedoom"
PAIN_PREFIX = "pain:"


def parse_seeds(text: str) -> range:
    """`7` or `1-10` (inclusive) as a range of seeds; raises ValueError for anything else."""
    first, _, last = text.partition("-")
    low, high = int(first), int(last or first)
    if high < low:
        raise ValueError(f"seed range {text!r} ends before it starts")
    return range(low, high + 1)


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", help="comma-separated; default is every training level")
    parser.add_argument("--policies", default=DEFAULT_POLICIES)
    parser.add_argument("--seeds", default="1-10", help="N or LOW-HIGH, inclusive")
    parser.add_argument("--decisions", type=int, default=20)
    parser.add_argument("--out", default=DEFAULT_OUT)
    return parser.parse_args(argv)


def wad_path(out: Path) -> Path:
    """Seam: where the Freedoom WAD is installed. `out` is unused; the WAD stays under data/."""
    from symbiont.act1.setup_assets import install_freedoom

    return install_freedoom(FREEDOOM_DIR)


def load_level(wad: Path, level: str) -> tuple[Any, MapKnowledge, RoomFinder]:
    """Seam: the only function that touches ViZDoom or the WAD."""
    from symbiont.act1.engine import make_game

    geometry = read_map(wad.read_bytes(), level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    return make_game(wad, level), knowledge, RoomFinder(geometry)


def episode_path(out: Path, episode: Episode) -> Path:
    return out / episode.level / f"{episode.session_id}.jsonl"


def how_it_ended(game: Any) -> str:
    if game.is_player_dead():
        return "died"
    if game.is_episode_finished():
        return "episode finished"
    return "decision cap"


def count_pains(records: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for tag in record.tags:
            if tag.startswith(PAIN_PREFIX):
                name = tag.removeprefix(PAIN_PREFIX)
                counts[name] = counts.get(name, 0) + 1
    return counts


def play_episode(
    game: Any, knowledge: MapKnowledge, rooms: RoomFinder, episode: Episode, decisions: int
) -> tuple[list[Any], int]:
    """The episode's records and its rejected-decision count; raises RuntimeError with no moves."""
    runs: list[MoveRun] = []
    game.set_seed(episode.seed)
    policy = policy_named(episode.policy, episode.seed)
    done = run_episode(
        game, policy.reply, decisions, RunLog(on_move=runs.append), knowledge=knowledge
    )
    if not runs:
        raise RuntimeError(f"no moves played: {episode.session_id}")
    rejected = sum(decision.status != "ok" for decision in done)
    return episode_records(episode, runs, rooms), rejected


def collect_episode(
    level_setup: tuple[Any, MapKnowledge, RoomFinder], episode: Episode, decisions: int, out: Path
) -> dict[str, Any]:
    """Play and write one episode; the file appears only when the episode finished cleanly."""
    game, knowledge, rooms = level_setup
    path = episode_path(out, episode)
    if path.exists():
        raise FileExistsError(f"{path} already exists; episodes are never overwritten")
    started = time.monotonic()
    try:
        records, rejected = play_episode(game, knowledge, rooms, episode, decisions)
    except Exception as error:
        error.add_note(f"while playing {episode.session_id}")
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        dump_jsonl(records, handle)
    return {
        "level": episode.level,
        "policy": episode.policy,
        "seed": episode.seed,
        "records": len(records),
        "seconds": round(time.monotonic() - started, 2),
        "rejected": rejected,
        "pains": count_pains(records),
        "ended": how_it_ended(game),
    }


def collect_level(level: str, wad: Path, args: argparse.Namespace, seeds: range) -> None:
    """One game per level, reseeded before each episode; the game is closed even on failure."""
    try:
        level_setup = load_level(wad, level)
    except Exception as error:
        error.add_note(f"while loading {level} (first seed {seeds[0]})")
        raise
    try:
        for policy in args.policies.split(","):
            for seed in seeds:
                summary = collect_episode(
                    level_setup, Episode(level, policy, seed), args.decisions, Path(args.out)
                )
                print(json.dumps(summary), flush=True)
    finally:
        level_setup[0].close()


def main(argv: list[str] | None = None) -> None:
    args = parse_arguments(argv)
    levels = args.levels.split(",") if args.levels else levels_in(LevelSplit.TRAINING)
    for level in levels:
        require_training(level)
    for policy in args.policies.split(","):
        policy_named(policy, 0)
    seeds = parse_seeds(args.seeds)
    wad = wad_path(Path(args.out))
    for level in levels:
        collect_level(level, wad, args, seeds)


if __name__ == "__main__":
    main()
