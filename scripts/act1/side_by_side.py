"""Side-by-side evidence clips from replayed episodes (replay_clip.py), synced by decision number.

Violation prevented: Paper Tiger in the evidence. A clip that shows the better-looking episode
and says nothing of the rest would meet the request and fail the need, so every closing frame
shows each arm's totals across ALL the episodes it was built from, and the footer says plainly
"exit reached at decision N" or "no exit within N decisions". Prevents Silent Fallback: an arm
whose sidecar is missing, or a pair that is not the same level and seed, stops with the reason
(a spec may say `"seeds": "named_in_titles"` when each side's title names its own seed).

    side_by_side.py pair --left L.json --right R.json --left-title T --right-title T \
        --subtitle TEXT --out FILE.mp4
    side_by_side.py reel --spec SPEC.json --out FILE.mp4
        SPEC: {"title": "...", "pairs": [{"left","right","left_title","right_title","subtitle"}]}

Every frame carries "plays Freedoom via ViZDoom" and "pain-point labels: the real tagger".
"""

import argparse
import json
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from symbiont.act1.game_pains import GamePain
from symbiont.act1.hook_overlay import PAIN_LABELS

CANVAS = (1920, 720)
HALF = (960, 540)  # each arm's 1280x720 panel clip, scaled
TOP = 100
BACKGROUND, INK, MUTED, ALERT = (16, 18, 24), (235, 238, 245), (140, 148, 165), (214, 60, 52)
CLOSING_SECONDS = 5
DECISION_CAP = 16  # the prereg's per-episode cap; "no exit within N decisions" says it
EXITED = "exited"


@dataclass(frozen=True)
class Arm:
    """One side of a pair: its sidecar (replay_clip.py), its clip and the title shown above it."""

    sidecar: dict[str, Any]
    mp4: Path
    title: str


def load_arm(sidecar_path: str, title: str) -> Arm:
    """Raises FileNotFoundError when the sidecar or its clip is missing."""
    path = Path(sidecar_path).expanduser()
    return Arm(json.loads(path.read_text()), path.with_suffix(".mp4"), title)


def span_frames(sidecar: dict[str, Any], decision: int) -> tuple[int, int]:
    """The frame range of one decision; a decision that played no move has an empty range."""
    span = sidecar["spans"].get(str(decision))
    return (span["first_frame"], span["end_frame"]) if span else (0, 0)


def decision_count(left: dict[str, Any], right: dict[str, Any]) -> int:
    return max(left["decisions"], right["decisions"])


def outcome_text(sidecar: dict[str, Any], cap: int) -> str:
    """The episode's ending in plain words, from its own decision count and end reason."""
    if sidecar["ended"] == EXITED:
        return f"exit reached at decision {sidecar['decisions']}"
    if sidecar["ended"] == "decision_cap":
        return f"no exit within {cap} decisions"
    return (
        f"episode ended at decision {sidecar['decisions']} ({sidecar['ended'].replace('_', ' ')})"
    )


def footer_text(sidecar: dict[str, Any], decision: int, cap: int) -> str:
    """Live line while the arm is still deciding; its outcome once its last decision is done."""
    if decision + 1 >= sidecar["decisions"]:
        return outcome_text(sidecar, cap)
    return f"decision {decision + 1} of {cap}"


def totals(sidecars: list[dict[str, Any]]) -> dict[str, Any]:
    """One arm's counts across all its episodes: pains by kind, exits, decisions."""
    kinds = {pain.value: 0 for pain in GamePain}
    for sidecar in sidecars:
        for kind, count in sidecar["pains"].items():
            kinds[kind] += count
    return {
        "episodes": len(sidecars),
        "pains": kinds,
        "pain_total": sum(kinds.values()),
        "exits": sum(sidecar["ended"] == EXITED for sidecar in sidecars),
        "decisions": sum(sidecar["decisions"] for sidecar in sidecars),
    }


def check_pair(left: Arm, right: Arm, allow_seeds: str) -> None:
    """Same level always; same seed unless each side's seed is named in its own title."""
    if left.sidecar["level"] != right.sidecar["level"]:
        raise ValueError("a pair must be one level on both sides")
    if allow_seeds == "same" and left.sidecar["seed"] != right.sidecar["seed"]:
        raise ValueError("a pair must be one seed on both sides")


def frames_of(mp4: Path) -> Iterator[np.ndarray]:
    """Frames of a panel clip scaled to HALF, one at a time (a whole clip would be ~750 MB)."""
    size = HALF[0] * HALF[1] * 3
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-vf", f"scale={HALF[0]}:{HALF[1]}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]  # fmt: skip
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        while chunk := proc.stdout.read(size):
            yield np.frombuffer(chunk, np.uint8).reshape(HALF[1], HALF[0], 3)
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed reading {mp4}")


def take(frames: Iterator[np.ndarray], count: int) -> list[np.ndarray]:
    """`count` frames from the stream; raises RuntimeError if the clip is shorter than its log."""
    taken = [frame for _, frame in zip(range(count), frames, strict=False)]
    if len(taken) != count:
        raise RuntimeError(f"clip ended {count - len(taken)} frames early")
    return taken


class Painter:
    def __init__(self) -> None:
        self._draw: ImageDraw.ImageDraw
        self._font = {size: ImageFont.load_default(size=size) for size in (14, 20, 28, 34, 44)}

    def canvas(self) -> Image.Image:
        """A blank frame; later `text` calls draw on the most recent canvas."""
        image = Image.new("RGB", CANVAS, BACKGROUND)
        self._draw = ImageDraw.ImageDraw(image)
        return image

    def text(self, xy: tuple[int, int], text: str, size: int, color=INK):
        self._draw.text(xy, text, font=self._font[size], fill=color)

    def header(self, left: Arm, right: Arm, subtitle: str) -> None:
        self.text((24, 10), "ai-symbiont  |  plays Freedoom via ViZDoom  |  " + subtitle, 20, MUTED)
        self.text((24, 50), left.title, 34)
        self.text((984, 50), right.title, 34)

    def footer(self, lines: tuple[str, str], pains: tuple[int, int]) -> None:
        y = TOP + HALF[1] + 14
        for x, line, pain in ((24, lines[0], pains[0]), (984, lines[1], pains[1])):
            self.text((x, y), f"{line}   |   pain points so far: {pain}", 28)
        self.text(
            (24, CANVAS[1] - 34),
            "pain-point labels: the real tagger, nothing added by hand",
            14,
            MUTED,
        )

    def pair_frame(
        self, halves: tuple[np.ndarray, np.ndarray], head: Image.Image, foot: tuple
    ) -> bytes:
        image = head.copy()
        image.paste(Image.fromarray(halves[0]), (0, TOP))
        image.paste(Image.fromarray(halves[1]), (HALF[0] + 0, TOP))
        self._draw = ImageDraw.ImageDraw(image)
        self.footer(foot[0], foot[1])
        return image.tobytes()

    def closing(
        self, title: str, rows: tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]
    ) -> bytes:
        image = self.canvas()
        self.text((24, 10), "ai-symbiont  |  plays Freedoom via ViZDoom", 20, MUTED)
        self.text((24, 46), title, 34)
        for x, (name, total) in zip((24, 984), rows, strict=False):
            self.arm_totals(x, name, total)
        self.text(
            (24, CANVAS[1] - 34),
            "counts across every episode of the arm, not only the ones shown; "
            "pain-point labels: the real tagger",
            14,
            MUTED,
        )
        return image.tobytes()

    def arm_totals(self, x: int, name: str, total: dict[str, Any]) -> None:
        self.text((x, 130), name, 34)
        self.text(
            (x, 190),
            f"{total['episodes']} episode(s), {total['decisions']} decisions",
            28,
            MUTED,
        )
        self.text((x, 250), f"{total['pain_total']} pain points", 44, ALERT)
        for row, (pain, label) in enumerate(PAIN_LABELS.items()):
            self.text((x, 330 + row * 46), f"{label}: {total['pains'][pain.value]}", 28)
        self.text(
            (x, 540),
            f"exit reached in {total['exits']} of {total['episodes']} episode(s)",
            34,
        )


class Encoder:
    """Raw RGB frames in, H.264 MP4 out; failure raises and leaves no file."""

    def __init__(self, mp4: Path, fps: int):
        mp4.parent.mkdir(parents=True, exist_ok=True)
        self._mp4 = mp4
        self._proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", "x".join(map(str, CANVAS)), "-r", str(fps), "-i", "-", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-crf", "24", "-movflags", "+faststart", str(mp4)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip

    def add(self, frame: bytes) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(frame)

    def close(self) -> None:
        assert self._proc.stdin is not None and self._proc.stderr is not None
        self._proc.stdin.close()
        error = self._proc.stderr.read().decode()
        if self._proc.wait() != 0:
            self._mp4.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed writing {self._mp4}: {error.strip()}")


def pains_after(sidecar: dict[str, Any], decision: int) -> int:
    """Pain points up to and including this decision (the span's own running tally)."""
    done = [n for n in range(decision + 1) if str(n) in sidecar["spans"]]
    return sum(sidecar["spans"][str(done[-1])]["tally"].values()) if done else 0


def synced_halves(
    segments: list[list[np.ndarray]], held: list[np.ndarray]
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Both arms' frames for one decision; the shorter segment (or none) holds its last frame."""
    for number in range(max(len(segment) for segment in segments)):
        for side, segment in enumerate(segments):
            if segment:
                held[side] = segment[min(number, len(segment) - 1)]
        yield held[0], held[1]


def render_body(left: Arm, right: Arm, subtitle: str, out: Path) -> None:
    """For each decision both arms' segments, the shorter held on its last frame."""
    painter, encoder = Painter(), Encoder(out, left.sidecar["fps"])
    head = painter.canvas()
    painter.header(left, right, subtitle)
    streams = (frames_of(left.mp4), frames_of(right.mp4))
    held = [np.zeros((HALF[1], HALF[0], 3), np.uint8)] * 2
    arms = (left, right)
    for decision in range(decision_count(left.sidecar, right.sidecar)):
        spans = [span_frames(arm.sidecar, decision) for arm in arms]
        segments = [take(s, end - start) for s, (start, end) in zip(streams, spans, strict=True)]
        foot = (
            tuple(footer_text(arm.sidecar, decision, DECISION_CAP) for arm in arms),
            tuple(pains_after(arm.sidecar, decision) for arm in arms),
        )
        for halves in synced_halves(segments, held):
            encoder.add(painter.pair_frame(halves, head, foot))
    encoder.close()


def render_closing(title: str, rows: tuple, out: Path, fps: int) -> None:
    painter, encoder = Painter(), Encoder(out, fps)
    frame = painter.closing(title, rows)
    for _ in range(CLOSING_SECONDS * fps):
        encoder.add(frame)
    encoder.close()


def concatenate(parts: list[Path], out: Path) -> None:
    """Join same-encoding clips without re-encoding."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
        listing.write("".join(f"file '{part}'\n" for part in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    listing.name, "-c", "copy", str(out)], check=True)  # fmt: skip
    Path(listing.name).unlink()


def compile_arm(sidecars: list[str], title: str, out: Path) -> None:
    """One arm's episodes back to back (panel clips centered on the canvas), then its totals."""
    arms = [load_arm(path, title) for path in sidecars]
    fps = arms[0].sidecar["fps"]
    with tempfile.TemporaryDirectory() as scratch:
        closing = Path(scratch) / "closing.mp4"
        render_closing(title, ((title, totals([arm.sidecar for arm in arms])),), closing, fps)
        inputs = [item for arm in arms for item in ("-i", str(arm.mp4))] + ["-i", str(closing)]
        pads = "".join(
            f"[{n}:v]pad={CANVAS[0]}:{CANVAS[1]}:(ow-iw)/2:0,setsar=1[v{n}];"
            for n in range(len(arms))
        )
        joined = "".join(f"[v{n}]" for n in range(len(arms))) + f"[{len(arms)}:v]"
        graph = f"{pads}{joined}concat=n={len(arms) + 1}:v=1:a=0[out]"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
                        "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
                        "-movflags", "+faststart", str(out)], check=True)  # fmt: skip


def pair_from(spec: dict[str, Any]) -> tuple[Arm, Arm]:
    left, right = (
        load_arm(spec["left"], spec["left_title"]),
        load_arm(spec["right"], spec["right_title"]),
    )
    check_pair(left, right, spec.get("seeds", "same"))
    return left, right


def build(pairs: list[dict[str, Any]], title: str, out: Path) -> None:
    """Bodies of every pair, then one closing frame with each arm's totals across all of them."""
    with tempfile.TemporaryDirectory() as scratch:
        parts: list[Path] = []
        arms = [pair_from(spec) for spec in pairs]
        for number, ((left, right), spec) in enumerate(zip(arms, pairs, strict=True)):
            parts.append(Path(scratch) / f"body{number}.mp4")
            render_body(left, right, spec["subtitle"], parts[-1])
        rows = tuple(
            (arms[0][side].title, totals([pair[side].sidecar for pair in arms])) for side in (0, 1)
        )
        parts.append(Path(scratch) / "closing.mp4")
        render_closing(title, rows, parts[-1], arms[0][0].sidecar["fps"])
        out.parent.mkdir(parents=True, exist_ok=True)
        concatenate(parts, out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair")
    for name in ("left", "right", "left-title", "right-title", "subtitle", "out"):
        pair.add_argument(f"--{name}", required=True)
    reel = sub.add_parser("reel")
    reel.add_argument("--spec", required=True)
    reel.add_argument("--out", required=True)
    compilation = sub.add_parser("compile")
    compilation.add_argument("--sidecars", nargs="+", required=True)
    compilation.add_argument("--title", required=True)
    compilation.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "compile":
        compile_arm(args.sidecars, args.title, Path(args.out).expanduser())
    elif args.command == "pair":
        one = {"left": args.left, "right": args.right, "left_title": args.left_title,
               "right_title": args.right_title, "subtitle": args.subtitle}  # fmt: skip
        build([one], args.subtitle, Path(args.out).expanduser())
    else:
        spec = json.loads(Path(args.spec).read_text())
        build(spec["pairs"], spec["title"], Path(args.out).expanduser())


if __name__ == "__main__":
    main()
