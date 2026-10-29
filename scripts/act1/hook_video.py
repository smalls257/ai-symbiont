"""Draw the demo clip's frames and write them as MP4 and GIF (periphery: Pillow and ffmpeg).

ffmpeg exiting non-zero raises with its own error text and never leaves a half-written file as
"the clip". Pillow and ffmpeg are demo tooling, not project dependencies: `uv pip install pillow`
and ffmpeg from the system.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from symbiont.act1.hook_overlay import PAIN_LABELS, MoveCard

CANVAS = (1280, 720)
GAME_AREA = (960, 720)  # 4:3 screen at 1.5x
PANEL_X = GAME_AREA[0]
BACKGROUND = (16, 18, 24)
INK = (235, 238, 245)
MUTED = (140, 148, 165)
ALERT = (214, 60, 52)
GIF_WIDTH = 640
GIF_FPS = 12
MOVE_CHARS = 22
RESULT_CHARS = 30


@dataclass(frozen=True)
class ClipTitle:
    """The header lines: what is playing and under which policy (never implied to be a model)."""

    level: str
    policy_label: str


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[: chars - 1] + "…"


class PanelPainter:
    """Composes one 1280x720 frame: the game on the left, the step panel on the right."""

    def __init__(self, title: ClipTitle):
        self._title = title
        self._fonts = {size: _font(size) for size in (12, 15, 18, 22, 26, 44, 40)}

    def frame(
        self, screen: np.ndarray, card: MoveCard, counts: dict[str, int], *, shout: bool
    ) -> bytes:
        """RGB bytes of one frame; `shout` shows the move's outcome and pain banner."""
        canvas = Image.new("RGB", CANVAS, BACKGROUND)
        game = Image.fromarray(np.moveaxis(screen, 0, -1)).resize(GAME_AREA, Image.BILINEAR)
        canvas.paste(game, (0, 0))
        draw = ImageDraw.Draw(canvas)
        self._header(draw)
        self._move(draw, card, shout=shout)
        self._tally(draw, counts, card if shout else None)
        if shout and card.pains:
            self._banner(draw, " + ".join(card.pains))
        return canvas.tobytes()

    def _text(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *style) -> None:
        size, color = style
        draw.text(xy, text, font=self._fonts[size], fill=color)

    def _header(self, draw: ImageDraw.ImageDraw) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 24), "ai-symbiont", 26, INK)
        self._text(draw, (x, 60), "plays Freedoom via ViZDoom", 15, MUTED)
        self._text(draw, (x, 84), f"{self._title.level}  |  {self._title.policy_label}", 15, MUTED)

    def _move(self, draw: ImageDraw.ImageDraw, card: MoveCard, *, shout: bool) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 140), "STEP", 12, MUTED)
        self._text(draw, (x, 156), f"{card.step:02d}", 44, INK)
        self._text(draw, (x, 232), "CHOSEN MOVE", 12, MUTED)
        self._text(draw, (x, 250), _clip(card.move, MOVE_CHARS), 22, INK)
        self._text(draw, (x, 300), "RESULT", 12, MUTED)
        result = _clip(card.outcome, RESULT_CHARS) if shout else "playing..."
        self._text(draw, (x, 318), result, 15, INK if shout else MUTED)

    def _tally(
        self, draw: ImageDraw.ImageDraw, counts: dict[str, int], fired: MoveCard | None
    ) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 400), "PAIN POINTS SO FAR", 12, MUTED)
        for row, label in enumerate(PAIN_LABELS.values()):
            y = 424 + row * 40
            hot = fired is not None and label in fired.pains
            self._text(draw, (x, y), label, 18, ALERT if hot else INK)
            self._text(draw, (x + 230, y), str(counts.get(label, 0)), 22, ALERT if hot else INK)
        self._text(draw, (x, 660), "labels: the real tagger,", 12, MUTED)
        self._text(draw, (x, 678), "nothing added by hand", 12, MUTED)

    def _banner(self, draw: ImageDraw.ImageDraw, label: str) -> None:
        draw.rectangle((0, GAME_AREA[1] - 96, GAME_AREA[0], GAME_AREA[1]), fill=ALERT)
        self._text(draw, (28, GAME_AREA[1] - 82), label.upper(), 40, INK)


class ClipSink:
    """Pipes raw frames into ffmpeg and finishes with an MP4 (and a GIF made from it)."""

    def __init__(self, mp4: Path, fps: int):
        self._mp4, self._fps, self.frames = mp4, fps, 0
        mp4.parent.mkdir(parents=True, exist_ok=True)
        self._ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", "x".join(map(str, CANVAS)), "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-movflags", "+faststart",
             str(mp4)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip

    def add(self, frame: bytes) -> None:
        assert self._ffmpeg.stdin is not None
        self._ffmpeg.stdin.write(frame)
        self.frames += 1

    def finish(self) -> float:
        """Close the MP4; returns its duration in seconds. Raises RuntimeError on ffmpeg failure."""
        assert self._ffmpeg.stdin is not None
        self._ffmpeg.stdin.close()
        error = self._ffmpeg.stderr.read().decode() if self._ffmpeg.stderr else ""
        if self._ffmpeg.wait() != 0:
            self._mp4.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg failed writing {self._mp4}: {error.strip()}")
        return self.frames / self._fps


def make_gif(mp4: Path, gif: Path) -> None:
    """A palette-optimized GIF from the MP4. Raises CalledProcessError on ffmpeg failure."""
    palette = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos"
    graph = f"{palette},split[a][b];[a]palettegen[p];[b][p]paletteuse"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", graph, str(gif)], check=True
    )
