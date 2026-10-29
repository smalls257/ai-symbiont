"""Collect self-play and Glimmer episodes into gitignored data/: records plus a decision log.

A held-out level, an existing episode file, a move-less episode or a failing level stops the run
naming it; only `load_level` touches ViZDoom or the WAD. Glimmer arms (`glimmer_plain`,
`glimmer_personal`) share one adapter server under `--adapters K` and differ only in adapter
scales. Held-out levels need `--scored PREREG` with a frozen, committed prereg (prereg/AGENTS.md).
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.act1.episode import MapKnowledge, RunLog, run_episode
from symbiont.act1.episode_records import Episode, EpisodeEnd, episode_records
from symbiont.act1.glimmer import GlimmerArm, plain_and_personal, plain_and_personal_by_model
from symbiont.act1.levels import LevelSplit, levels_in, require_training, split_of
from symbiont.act1.map_index import build_index
from symbiont.act1.navmap import build_navmap
from symbiont.act1.policies import Policy, policy_named
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveRun
from symbiont.act1.wad import read_map
from symbiont.records.schema import dump_jsonl

DEFAULT_POLICIES = "random,scripted_explorer"
DEFAULT_OUT = "data/act1/episodes"
FREEDOOM_DIR = Path("data") / "freedoom"
PAIN_PREFIX = "pain:"
GLIMMER_ARMS = ("glimmer_plain", "glimmer_personal")
DEFAULT_MODEL = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
FROZEN_MARK = "**FROZEN"  # a prereg's status line after the owner's freeze commit


class PreregNotFrozenError(RuntimeError):
    """A scored run was asked for without a frozen, committed, unchanged prereg."""


@dataclass(frozen=True)
class Plan:
    """How every episode of this run is played: decision cap and the policy for (name, seed)."""

    decisions: int
    make_policy: Callable[[str, int], Policy]


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
    parser.add_argument("--glimmer-model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--adapters", type=int, default=0, help="adapters the Glimmer server holds; 0: none"
    )
    parser.add_argument(
        "--personal-model", help="served model name of the personal arm (the adapter's own name)"
    )
    parser.add_argument("--personal-adapter", type=int, default=0, help="the Freedoom adapter")
    parser.add_argument("--scored", type=Path, help="frozen prereg; required for held-out levels")
    return parser.parse_args(argv)


def glimmer_arms(args: argparse.Namespace) -> dict[str, GlimmerArm]:
    """The Glimmer arms this run can play; the URL comes from SYMBIONT_GLIMMER_URL, never a file.

    Without adapters only plain Glimmer exists (history collection on the production server).
    """
    url = os.environ.get("SYMBIONT_GLIMMER_URL")
    if not url:
        raise RuntimeError("SYMBIONT_GLIMMER_URL is not set; Glimmer arms need the server URL")
    if args.personal_model:
        arms = plain_and_personal_by_model(url, args.glimmer_model, args.personal_model)
        return {arm.name: arm for arm in arms}
    if args.adapters == 0:
        return {"glimmer_plain": GlimmerArm("glimmer_plain", url, args.glimmer_model)}
    arms = plain_and_personal(url, args.glimmer_model, args.adapters, args.personal_adapter)
    return {arm.name: arm for arm in arms}


def policy_maker(args: argparse.Namespace) -> Callable[[str, int], Policy]:
    """Policy by name; Glimmer arms ignore the seed (the game is reseeded instead)."""
    names = args.policies.split(",")
    arms = glimmer_arms(args) if set(names) & set(GLIMMER_ARMS) else {}
    for name in names:
        if name in GLIMMER_ARMS and name not in arms:
            raise ValueError(
                f"{name} needs --personal-model or --adapters: the personal arm is an adapter"
            )
        if name not in GLIMMER_ARMS:
            policy_named(name, 0)

    def make(name: str, seed: int) -> Policy:
        if name in arms:
            return Policy(name, arms[name].reply)
        return policy_named(name, seed)

    return make


def status_line(text: str) -> str:
    """The prereg's first bold line; a draft that only mentions the mark is not frozen."""
    return next((line for line in text.splitlines() if line.startswith("**")), "")


def require_frozen_prereg(prereg: Path) -> str:
    """The prereg's sha256 when it is frozen, committed and unchanged; raises otherwise."""
    if not prereg.is_file():
        raise PreregNotFrozenError(f"{prereg} does not exist")
    if not status_line(prereg.read_text(encoding="utf-8")).startswith(FROZEN_MARK):
        raise PreregNotFrozenError(f"{prereg} is not frozen (its status line is not {FROZEN_MARK})")
    where = {"cwd": prereg.parent, "capture_output": True, "check": False}
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", prereg.name], **where)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", prereg.name], **where)
    if tracked.returncode != 0 or changed.returncode != 0:
        raise PreregNotFrozenError(f"{prereg} is not committed, or differs from HEAD")
    return hashlib.sha256(prereg.read_bytes()).hexdigest()


def check_levels(levels: list[str], scored: Path | None) -> str | None:
    """Training levels pass; held-out ones only in a scored run. Returns the prereg sha256."""
    for level in levels:
        split_of(level)
    if scored is None:
        for level in levels:
            require_training(level)
        return None
    return require_frozen_prereg(scored)


def wad_path() -> Path:
    """Seam: where the Freedoom WAD is installed; it always stays under data/."""
    from symbiont.act1.setup_assets import install_freedoom

    return install_freedoom(FREEDOOM_DIR)


def load_level(wad: Path, level: str, hud: str = "off") -> tuple[Any, MapKnowledge, RoomFinder]:
    """Seam: the only function that touches ViZDoom or the WAD."""
    from symbiont.act1.engine import HudStyle, make_game

    geometry = read_map(wad.read_bytes(), level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    return make_game(wad, level, hud=HudStyle(hud)), knowledge, RoomFinder(geometry)


def episode_path(out: Path, episode: Episode) -> Path:
    return out / episode.level / f"{episode.session_id}.jsonl"


def decisions_path(out: Path, episode: Episode) -> Path:
    """The decision log beside the records: observation, reply, tokens and seconds per decision."""
    return out / episode.level / f"{episode.session_id}.decisions.jsonl"


def how_it_ended(game: Any) -> EpisodeEnd:
    """Death first, then finished (a timeout is not an exit), else the decision cap ran out."""
    if game.is_player_dead():
        return EpisodeEnd.DIED
    if game.is_episode_finished():
        timed_out = game.get_episode_time() >= game.get_episode_timeout()
        return EpisodeEnd.TIMED_OUT if timed_out else EpisodeEnd.EXITED
    return EpisodeEnd.DECISION_CAP


def count_pains(records: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for tag in record.tags:
            if tag.startswith(PAIN_PREFIX):
                name = tag.removeprefix(PAIN_PREFIX)
                counts[name] = counts.get(name, 0) + 1
    return counts


def play_episode(
    level_setup: tuple[Any, MapKnowledge, RoomFinder], episode: Episode, plan: Plan, log: Path
) -> tuple[list[Any], list[Any], EpisodeEnd]:
    """Records, decisions and ending; the decision log is appended as play goes.

    Raises RuntimeError when no move was played.
    """
    game, knowledge, rooms = level_setup
    runs: list[MoveRun] = []
    game.set_seed(episode.seed)
    policy = plan.make_policy(episode.policy, episode.seed)
    header = {"session_id": episode.session_id, "policy": episode.policy}
    run_log = RunLog(log, header, on_move=runs.append)
    done = run_episode(game, policy.reply, plan.decisions, run_log, knowledge=knowledge)
    if not runs:
        raise RuntimeError(f"no moves played: {episode.session_id}")
    ended = how_it_ended(game)
    return episode_records(episode, runs, rooms, ended), done, ended


def _tokens(done: list[Any], field: str) -> int | None:
    """Summed server tokens, or None when no decision called a model (scripted policies)."""
    counts = [getattr(decision, field) for decision in done]
    return None if all(count is None for count in counts) else sum(c or 0 for c in counts)


def collect_episode(
    level_setup: tuple[Any, MapKnowledge, RoomFinder], episode: Episode, plan: Plan, out: Path
) -> dict[str, Any]:
    """Play and write one episode.

    Records go to `<path>.partial` and are renamed to `<path>` once written, so the final path
    only ever holds a finished episode and the overwrite check cannot mistake a torn one for it.
    """
    path = episode_path(out, episode)
    if path.exists():
        raise FileExistsError(f"{path} already exists; episodes are never overwritten")
    started = time.monotonic()
    try:
        records, done, ended = play_episode(
            level_setup, episode, plan, decisions_path(out, episode)
        )
    except Exception as error:
        error.add_note(f"while playing {episode.session_id}")
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("w") as handle:
        dump_jsonl(records, handle)
    partial.rename(path)
    return {
        "level": episode.level,
        "policy": episode.policy,
        "seed": episode.seed,
        "split": split_of(episode.level).value,
        "records": len(records),
        "decisions": len(done),
        "seconds": round(time.monotonic() - started, 2),
        "model_seconds": round(sum(decision.model_seconds for decision in done), 2),
        "tokens_in": _tokens(done, "tokens_in"),
        "tokens_out": _tokens(done, "tokens_out"),
        "rejected": sum(decision.status != "ok" for decision in done),
        "pains": count_pains(records),
        "ended": ended.value,
    }


def collect_level(level: str, wad: Path, args: argparse.Namespace, plan: Plan) -> None:
    """One game per level, reseeded before each episode; the game is closed even on failure."""
    try:
        level_setup = load_level(wad, level)
    except Exception as error:
        error.add_note(f"while loading {level} (seeds {args.seeds})")
        raise
    try:
        for seed in parse_seeds(args.seeds):  # seed-major: arms alternate on one level and seed
            for policy in args.policies.split(","):
                summary = collect_episode(
                    level_setup, Episode(level, policy, seed), plan, Path(args.out)
                )
                print(json.dumps(summary), flush=True)
    finally:
        level_setup[0].close()


def main(argv: list[str] | None = None) -> None:
    args = parse_arguments(argv)
    levels = args.levels.split(",") if args.levels else list(levels_in(LevelSplit.TRAINING))
    prereg_sha = check_levels(levels, args.scored)
    plan = Plan(args.decisions, policy_maker(args))
    parse_seeds(args.seeds)
    if prereg_sha is not None:
        print(json.dumps({"scored": str(args.scored), "prereg_sha256": prereg_sha}), flush=True)
    wad = wad_path()
    for level in levels:
        collect_level(level, wad, args, plan)


if __name__ == "__main__":
    main()
