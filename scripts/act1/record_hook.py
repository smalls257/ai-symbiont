"""Record the opening-hook clip: one policy plays Freedoom via ViZDoom, with a pain-point panel.

Panel labels come only from `tag_pains`, the tagger that writes the episode log; this script
cannot type a label. The clip shows game tics only (model waits are cut); a clip outside 20 to
30 s is reported, never padded or looped. The real model: scripts/act1/record_glimmer_hook.sh.
Usage: uv run python scripts/act1/record_hook.py --policy random --seed 3 --out <dir>
"""

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hook_video import ClipSink, ClipTitle, PanelPainter, make_gif

from symbiont.act1.episode import MapKnowledge, RunLog, run_episode
from symbiont.act1.frame_tap import FrameTap
from symbiont.act1.game_pains import tag_pains
from symbiont.act1.glimmer import ReplyFn, chat_reply
from symbiont.act1.hook_overlay import MoveCard, banner_start, card_for, tally
from symbiont.act1.levels import require_training
from symbiont.act1.map_index import build_index
from symbiont.act1.navmap import build_navmap
from symbiont.act1.policies import policy_named
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveRun
from symbiont.act1.wad import read_map

FREEDOOM_DIR = Path("data") / "freedoom"
GLIMMER_MODEL = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
GLIMMER_URL_VARIABLE = "SYMBIONT_GLIMMER_URL"
TARGET_SECONDS = (20.0, 30.0)
# Median and mean seconds per decision of Glimmer at "Reasoning strength: low" [measured: T37
# reasoning-strength gate, fixed_low arm, 30 items, 966.5 s total; one slot shared with a run].
GLIMMER_SECONDS_PER_DECISION = 32.2


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--level", default="MAP01")
    parser.add_argument("--policy", default="random", help="random, scripted_explorer or glimmer")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=25.0, help="clip length, 20 to 30")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--stride", type=int, default=2, help="game tics per frame (2 = 1.7x speed)"
    )
    parser.add_argument("--decisions", type=int, default=60, help="cap on model decisions")
    parser.add_argument("--out", default=str(Path.home() / "symbiont-runs" / "hook"))
    parser.add_argument("--glimmer-url", help=f"default: ${GLIMMER_URL_VARIABLE} (ends in /v1)")
    parser.add_argument("--model", default=GLIMMER_MODEL)
    return parser.parse_args(argv)


def expected_glimmer_seconds(decisions: int) -> float:
    return decisions * GLIMMER_SECONDS_PER_DECISION


def reply_function(args: argparse.Namespace) -> tuple[ReplyFn, str]:
    """The policy's reply function and the label the panel shows. Raises SystemExit if no URL."""
    if args.policy != "glimmer":
        return policy_named(args.policy, args.seed).reply, f"{args.policy} policy"
    url = args.glimmer_url or os.environ.get(GLIMMER_URL_VARIABLE)
    if not url:
        raise SystemExit(f"--policy glimmer needs --glimmer-url or ${GLIMMER_URL_VARIABLE}")
    return lambda prompt: chat_reply(url, args.model, prompt), "Glimmer, reasoning low"


def load_level(level: str) -> tuple[Any, MapKnowledge, RoomFinder]:
    """Seam: the only place that touches ViZDoom and the WAD."""
    from symbiont.act1.engine import FrameSize, make_game
    from symbiont.act1.setup_assets import install_freedoom

    wad = install_freedoom(FREEDOOM_DIR)
    geometry = read_map(wad.read_bytes(), level)
    index = build_index(geometry)
    knowledge = MapKnowledge(index, build_navmap(geometry, index))
    return make_game(wad, level, frame_size=FrameSize.CLIP), knowledge, RoomFinder(geometry)


def move_recorder(
    tap: FrameTap, rooms: RoomFinder, painter: PanelPainter, sink: ClipSink
) -> Callable[[MoveRun], None]:
    """The observer `run_episode` calls after each move: tag it, then paint and write its frames."""
    runs: list[MoveRun] = []
    cards: list[MoveCard] = []

    def on_move(run: MoveRun) -> None:
        runs.append(run)
        card = card_for(len(runs) - 1, run, tag_pains(runs, rooms)[-1])
        frames = tap.take_frames()
        cards.append(card)
        counts = tally(cards)  # includes this move: its banner shows as its frames reach the end
        start = banner_start(len(frames))
        for number, screen in enumerate(frames):
            sink.add(painter.frame(screen, card, dict(counts), shout=number >= start))

    return on_move


def record(args: argparse.Namespace) -> dict[str, Any]:
    """Play one episode and write <out>/<name>.mp4 and .gif; returns the summary."""
    require_training(args.level)
    reply, policy_label = reply_function(args)
    game, knowledge, rooms = load_level(args.level)
    name = f"{args.level}-{args.policy}-s{args.seed}"
    out = Path(args.out).expanduser()
    tap = FrameTap(game, args.stride, round(args.seconds * args.fps * args.stride))
    sink = ClipSink(out / f"{name}.mp4", args.fps)
    painter = PanelPainter(ClipTitle(args.level, policy_label))
    started = time.monotonic()
    try:
        run_log = RunLog(on_move=move_recorder(tap, rooms, painter, sink))
        done = run_episode(tap, reply, args.decisions, run_log, knowledge=knowledge)
    finally:
        game.close()
    seconds = sink.finish()
    make_gif(out / f"{name}.mp4", out / f"{name}.gif")
    return {
        "clip": str(out / f"{name}.mp4"), "gif": str(out / f"{name}.gif"),
        "clip_seconds": round(seconds, 1), "decisions": len(done),
        "budget_spent": tap.budget_spent, "wall_seconds": round(time.monotonic() - started, 1),
    }  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    args = parse_arguments(argv)
    if args.policy == "glimmer":
        minutes = expected_glimmer_seconds(args.decisions) / 60
        print(
            f"expected Glimmer time: about {minutes:.1f} min for up to {args.decisions} decisions "
            f"({GLIMMER_SECONDS_PER_DECISION} s each, reasoning low [measured, T37 gate]); "
            "the clip ends sooner if the exit is reached",
            flush=True,
        )
    summary = record(args)
    print(summary, flush=True)
    low, high = TARGET_SECONDS
    if not low <= summary["clip_seconds"] <= high:
        print(
            f"WARNING: clip is {summary['clip_seconds']} s, outside {low}-{high} s", file=sys.stderr
        )


if __name__ == "__main__":
    main()
