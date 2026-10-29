"""Record the pre-named clips by replaying the scored games' logged decisions (stage panel).

A replay that drifts from the logged game raises and writes no clip. A named game that is
ungraded is replaced by the next seed on the same map, and the swap is written to clips.json.

Usage: record_card_clips.py --state STATE --episodes DIR --out DIR --wad WAD [--clips MAP:SEED,...]
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evolve"))
import script_paths  # noqa: E402 - the evolve scripts directory is added just above

script_paths.add_script_dirs()

import frozen_cards  # noqa: E402 - needs the sibling path added above
import replay_clip  # noqa: E402
import run_state  # noqa: E402
import side_by_side  # noqa: E402

from symbiont.act1.engine import HudStyle  # noqa: E402
from symbiont.act1.game_fitness import Case, Grade  # noqa: E402
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting  # noqa: E402

CLIPS = (("MAP04", 2001), ("MAP08", 2001), ("MAP12", 2001))
LABELS = {
    "none": ("spark_nocard", "Muse Spark, no card"),
    "mined": ("spark_mined", "Muse Spark + mined card"),
    "strong": ("spark_strong", "Muse Spark + strong card"),
}
SWAP_STEP = 1  # the next seed on the same map, and nothing else
TITLE = "Muse Spark on held-out Freedoom maps, with and without the card"


class NoGradedClipError(RuntimeError):
    """The named game and its one allowed swap were both ungraded for some arm."""


def graded_case(games: dict[str, Any], level: str, seed: int) -> bool:
    """Whether every arm has a graded game on this case in the state file."""
    case = Case(level, seed, NORMAL_SKILL, CutSetting.NONE)
    for card in frozen_cards.ARMS.values():
        stored = games.get(run_state.game_key(card.card_id, case))
        if stored is None or stored["grade"] != Grade.GRADED.value:
            return False
    return True


def choose_seed(games: dict[str, Any], level: str, seed: int) -> tuple[int, bool]:
    """The named seed, or the next one if the named game is ungraded (the only substitution)."""
    if graded_case(games, level, seed):
        return seed, False
    if graded_case(games, level, seed + SWAP_STEP):
        return seed + SWAP_STEP, True
    raise NoGradedClipError(
        f"{level}: seeds {seed} and {seed + SWAP_STEP} are not graded in every arm"
    )


def record_game(
    arm: str, level: str, seed: int, where: dict[str, Path], games: dict[str, Any]
) -> Path:
    """Replay one logged game into an mp4 and a sidecar; returns the sidecar path."""
    card = frozen_cards.ARMS[arm]
    policy, _ = LABELS[arm]
    case = Case(level, seed, NORMAL_SKILL, CutSetting.NONE)
    log = where["episodes"] / f"{card.card_id}-{level}-s{seed}.jsonl"
    stored = games[run_state.game_key(card.card_id, case)]
    logged = dict(stored["pains"])
    original, original_load = replay_clip.logged_pains, replay_clip.load_level
    replay_clip.logged_pains = lambda *_: logged  # the pains come from the stored result
    # The games were played with the screen's status bar off, so the replay must be too: a
    # different bar changes the depth buffer and with it the layout line the player read.
    replay_clip.load_level = lambda wad, level, _hud: played_like(wad, level, seed, original_load)
    try:
        args = SimpleNamespace(level=level, policy=policy, seed=seed, out=str(where["out"]))
        replay_clip.ARM_LABELS[policy] = LABELS[arm][1]
        replay_with_log(args, log, where["out"])
    finally:
        replay_clip.logged_pains = original
        replay_clip.load_level = original_load
    return where["out"] / f"{level}-{policy}-s{seed}.json"


class SeedFixed:
    """A game that ignores a later set_seed: the scored game was seeded once, at init."""

    def __init__(self, game: Any):
        self._game = game

    def set_seed(self, _seed: int) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._game, name)


def played_like(wad: Path, level: str, seed: int, original_load: Any) -> Any:
    """The level as the scored player loaded it, including its extra prior new_episode."""
    from symbiont.act1.engine import Start, make_game

    _, knowledge, rooms = original_load(wad, level, HudStyle.OFF)
    game = make_game(wad, level, Start(seed, NORMAL_SKILL), hud=HudStyle.OFF)
    game.new_episode()
    return SeedFixed(game), knowledge, rooms


def replay_with_log(args: SimpleNamespace, log: Path, out: Path) -> None:
    """replay_clip's replay, reading the decision log from `log` instead of a fixed layout."""
    stem = f"{args.level}-{args.policy}-s{args.seed}"
    staged = out / "_logs" / args.level
    staged.mkdir(parents=True, exist_ok=True)
    (staged / f"{stem}.decisions.jsonl").write_bytes(log.read_bytes())
    args.episodes = str(out / "_logs")
    out.mkdir(parents=True, exist_ok=True)
    replay_clip.replay(args)


def main(argv: list[str] | None = None) -> int:
    """Record every named clip for all three arms and the no-card against mined reel."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wad", type=Path, required=True)
    parser.add_argument("--clips", help="MAP:SEED,... (default: the three named in the prereg)")
    args = parser.parse_args(argv)
    games = json.loads(args.state.read_text())["games"]
    where = {"episodes": args.episodes, "out": args.out}
    chosen, pairs = [], []
    named = (
        [(c.split(":")[0], int(c.split(":")[1])) for c in args.clips.split(",")]
        if args.clips
        else CLIPS
    )
    for level, seed in named:
        used, swapped = choose_seed(games, level, seed)
        chosen.append({"level": level, "named_seed": seed, "seed": used, "swapped": swapped})
        sidecars = {arm: record_game(arm, level, used, where, games) for arm in frozen_cards.ARMS}
        pairs.append(
            {
                "left": str(sidecars["none"]),
                "right": str(sidecars["mined"]),
                "left_title": LABELS["none"][1],
                "right_title": LABELS["mined"][1],
                "subtitle": f"{level}, seed {used}, the same map and seed",
            }
        )
    (args.out / "clips.json").write_text(json.dumps(chosen, indent=1))
    side_by_side.build(pairs, TITLE, args.out / "reel-none-vs-mined.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
