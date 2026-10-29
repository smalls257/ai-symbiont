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

from symbiont.act1.hook_overlay import PAIN_LABELS, MoveCard, PlayerStats

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
RESULT_CHARS = 32
RESULT_LINES = 2


@dataclass(frozen=True)
class ClipTitle:
    """The header lines: what is playing and under which policy (never implied to be a model)."""

    level: str
    policy_label: str


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[: chars - 1] + "…"


def wrap_result(text: str) -> list[str]:
    """The result in at most two lines of RESULT_CHARS; a longer one ends in "..." on line two.

    The cut is always shown, never silent, and the full text is in the episode's own records.
    """
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > RESULT_CHARS:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    if len(lines) > RESULT_LINES:
        lines = [lines[0], _clip(" ".join(lines[1:]), RESULT_CHARS)]
    return [_clip(entry, RESULT_CHARS) for entry in lines]


class PanelPainter:
    """Composes one 1280x720 frame: the game on the left, the step panel on the right."""

    def __init__(self, title: ClipTitle):
        self._title = title
        self._fonts = {size: _font(size) for size in (13, 16, 18, 20, 22, 26, 32)}

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
        if card.stats is not None:
            self._player(draw, card.stats)
        self._tally(draw, counts, card if shout else None)
        if shout and card.pains:
            self._banner(draw, " + ".join(card.pains))
        return canvas.tobytes()

    def _text(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *style) -> None:
        size, color = style
        draw.text(xy, text, font=self._fonts[size], fill=color)

    def _header(self, draw: ImageDraw.ImageDraw) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 16), "ai-symbiont", 26, INK)
        self._text(draw, (x, 50), "plays Freedoom via ViZDoom", 16, MUTED)
        self._text(draw, (x, 72), f"{self._title.level}  |  {self._title.policy_label}", 16, MUTED)

    def _move(self, draw: ImageDraw.ImageDraw, card: MoveCard, *, shout: bool) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 104), f"STEP  {card.step:02d}", 22, INK)
        self._text(draw, (x, 140), "CHOSEN MOVE", 13, MUTED)
        self._text(draw, (x, 156), _clip(card.move, MOVE_CHARS), 20, INK)
        self._text(draw, (x, 192), "RESULT", 13, MUTED)
        lines = wrap_result(card.outcome) if shout else ["playing..."]
        for row, line in enumerate(lines):
            self._text(draw, (x, 208 + row * 22), line, 16, INK if shout else MUTED)

    def _player(self, draw: ImageDraw.ImageDraw, stats: PlayerStats) -> None:
        x = PANEL_X + 24
        status = "DEAD" if stats.dead else "alive"
        self._text(draw, (x, 262), "PLAYER (game counters)", 13, MUTED)
        rows = (
            f"health {stats.health}   armor {stats.armor}   ammo {stats.ammo}",
            f"kills {stats.kills}   items {stats.items}   secrets {stats.secrets}",
            f"damage dealt {stats.damage_dealt}   taken {stats.damage_taken}",
            f"status: {status}",
        )
        for row, line in enumerate(rows):
            color = ALERT if stats.dead and row == len(rows) - 1 else INK
            self._text(draw, (x, 280 + row * 24), line, 16, color)

    def _tally(
        self, draw: ImageDraw.ImageDraw, counts: dict[str, int], fired: MoveCard | None
    ) -> None:
        x = PANEL_X + 24
        self._text(draw, (x, 392), "PAIN POINTS SO FAR", 13, MUTED)
        for row, label in enumerate(PAIN_LABELS.values()):
            y = 412 + row * 34
            hot = fired is not None and label in fired.pains
            self._text(draw, (x, y), label, 20, ALERT if hot else INK)
            self._text(draw, (x + 240, y), str(counts.get(label, 0)), 22, ALERT if hot else INK)
        self._text(draw, (x, 660), "labels: the real tagger,", 13, MUTED)
        self._text(draw, (x, 678), "nothing added by hand", 13, MUTED)

    def _banner(self, draw: ImageDraw.ImageDraw, label: str) -> None:
        draw.rectangle((0, GAME_AREA[1] - 96, GAME_AREA[0], GAME_AREA[1]), fill=ALERT)
        self._text(draw, (28, GAME_AREA[1] - 82), label.upper(), 32, INK)


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

    def discard(self) -> None:
        """Close ffmpeg and delete the MP4: a clip that must not exist (a drifted replay)."""
        assert self._ffmpeg.stdin is not None
        self._ffmpeg.stdin.close()
        self._ffmpeg.wait()
        self._mp4.unlink(missing_ok=True)

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
