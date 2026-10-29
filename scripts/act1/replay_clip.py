"""Render a played Glimmer episode as a hook clip by replaying its logged replies (no model call).

Violation prevented: Silent Fallback in the evidence video. A replay that drifted from the game
the model really played would show moves nobody made, so every decision's logged observation
must appear in the replayed prompt, and the replayed pain totals must equal the pains the
episode's own records carry; either mismatch raises `ReplayDriftError` and writes no clip. The
panel is the hook recorder's (step, chosen move, result, live tally from the real tagger).
Prevents Computational Friction as well: a clip costs seconds of CPU, not another 8 minutes of
Glimmer time.

Writes <out>/<arm>-<level>-s<seed>.mp4 and a .json sidecar (frame range and running tally per
decision, how the episode ended) that side_by_side.py reads. Counts only, never text.

    uv run python scripts/act1/replay_clip.py --episodes DIR --level MAP02 --policy glimmer_plain \
        --seed 3 --out ~/symbiont-runs/act1eval/video
"""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from collect_episodes import count_pains, how_it_ended, load_level, wad_path
from hook_video import ClipSink
from segment_recorder import ClipOutput, SegmentRecorder
from stage_panel import StagePainter, title_card

from symbiont.act1.engine import HudStyle
from symbiont.act1.episode import Decision, RunLog, load_run_log, run_episode
from symbiont.act1.frame_tap import FrameTap
from symbiont.act1.glimmer import Reply, ReplyFn
from symbiont.act1.hook_overlay import PAIN_LABELS, tally
from symbiont.act1.wad import read_map
from symbiont.records.schema import load_jsonl

FPS = 30
STRIDE = 2  # game tics per frame, as the hook recorder (1.7x speed)
TITLE_SECONDS = 2
TIC_BUDGET = 10**7  # a replay is never cut short: 16 decisions end long before this
PAIN_NAME_OF_LABEL = {label: pain.value for pain, label in PAIN_LABELS.items()}
ARM_LABELS = {
    "glimmer_plain": "Plain Glimmer",
    "glimmer_personal": "Glimmer + Freedoom adapter",
    "spark_low": "Muse Spark 1.3 (reasoning low)",
    "spark_medium": "Muse Spark 1.3 (reasoning medium)",
}


class ReplayDriftError(RuntimeError):
    """The replayed game differs from the logged one; no clip is written."""


def logged_replies(decisions: list[Decision], calls: list[int]) -> ReplyFn:
    """Replies in logged order; each call appends its decision number to `calls`.

    Raises ReplayDriftError when the prompt does not contain the logged observation, or when
    the replay asks for more decisions than were logged.
    """

    def reply(prompt: str) -> Reply:
        number = len(calls)
        if number >= len(decisions):
            raise ReplayDriftError(f"decision {number} was never logged")
        if decisions[number].observation not in prompt:
            raise ReplayDriftError(f"decision {number}: the replayed observation differs")
        calls.append(number)
        return Reply(decisions[number].reply, "stop", 0)

    return reply


def pains_by_name(counts: dict[str, int]) -> dict[str, int]:
    """Tag names (`wall_bump`) for panel labels (`wall bump`), counts only."""
    return {PAIN_NAME_OF_LABEL[label]: count for label, count in counts.items() if count}


def logged_pains(episodes: Path, level: str, stem: str) -> dict[str, int]:
    with (episodes / level / f"{stem}.jsonl").open(encoding="utf-8") as handle:
        return count_pains(list(load_jsonl(handle)))


def level_walls(level: str) -> list[Any]:
    """The level's wall segments for the mini-map backdrop, straight from the WAD."""
    geometry = read_map(wad_path().read_bytes(), level)
    return [
        (
            tuple(map(float, geometry.vertices[line.v1])),
            tuple(map(float, geometry.vertices[line.v2])),
        )
        for line in geometry.linedefs
    ]


def replay(args: argparse.Namespace) -> dict[str, Any]:
    """Replay one episode; returns the sidecar. Raises ReplayDriftError, FileNotFoundError."""
    stem = f"{args.level}-{args.policy}-s{args.seed}"
    episodes = Path(args.episodes).expanduser()
    decisions = load_run_log(episodes / args.level / f"{stem}.decisions.jsonl")
    game, knowledge, rooms = load_level(wad_path(), args.level, HudStyle.MINIMAL)
    tap = FrameTap(game, STRIDE, TIC_BUDGET)
    out = Path(args.out).expanduser()
    sink = ClipSink(out / f"{stem}.mp4", FPS)
    headline = f"{ARM_LABELS[args.policy]} plays Freedoom via ViZDoom, {args.level}"
    speaker = "Muse Spark" if args.policy.startswith("spark_") else "Glimmer"
    painter = StagePainter(headline, level_walls(args.level), speaker)
    for _ in range(TITLE_SECONDS * FPS):
        sink.add(
            title_card(
                headline, f"seed {args.seed}   the game and every move are replayed from the log"
            )
        )
    recorder = SegmentRecorder(tap, rooms, ClipOutput(sink, painter), decisions)
    try:
        game.set_seed(args.seed)
        run_episode(
            tap,
            logged_replies(decisions, recorder.calls),
            len(decisions),
            RunLog(on_move=recorder.on_move),
            knowledge=knowledge,
        )
        ended = how_it_ended(game)
    finally:
        game.close()
    return finish_clip(sink, recorder, ended.value, (args, stem, episodes))


def finish_clip(
    sink: ClipSink, recorder: SegmentRecorder, ended: str, where: tuple[Any, str, Path]
) -> dict[str, Any]:
    """Check the replay against the episode's records, then close the MP4 and write the sidecar."""
    args, stem, episodes = where
    replayed = pains_by_name(dict(tally(recorder.cards)))
    logged = logged_pains(episodes, args.level, stem)
    if replayed != logged:
        sink.discard()
        raise ReplayDriftError(f"{stem}: replayed pains {replayed} differ from logged {logged}")
    sink.finish()
    sidecar = {
        "arm": args.policy, "level": args.level, "seed": args.seed, "fps": FPS,
        "decisions": len(recorder.calls), "ended": ended, "pains": logged,
        "frames": sink.frames, "lead_frames": TITLE_SECONDS * FPS,
        "stats": asdict(recorder.last_stats), "path_ends": recorder.path_ends,
        "spans": {str(k): v for k, v in sorted(recorder.spans.items())},
    }  # fmt: skip
    out = Path(args.out).expanduser()
    (out / f"{stem}.json").write_text(json.dumps(sidecar, indent=1), encoding="utf-8")
    return sidecar


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--episodes", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--policy", choices=sorted(ARM_LABELS), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    started = time.monotonic()
    sidecar = replay(parse_arguments(argv))
    summary = {k: sidecar[k] for k in ("arm", "level", "seed", "decisions", "ended", "pains")}
    print(json.dumps({**summary, "seconds": round(time.monotonic() - started, 1)}), flush=True)


if __name__ == "__main__":
    main()
