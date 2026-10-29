"""One 1280x720 evidence frame: the game on the left, a lively stat panel on the right.

Violation prevented: Paper Tiger in the evidence video. Every number and mark on the panel comes
from a game counter, a logged field or the real tagger (`StageFrame` has no free-text slot but the
model's own logged reply), so a striking frame cannot say something the game did not. What the
logs do not hold, Glimmer's reasoning text, is not shown: the bubble says how long it thought and
how many characters of hidden reasoning there were, never an invented thought.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import stage_motion as motion
from PIL import Image, ImageDraw
from stage_style import (
    ALERT,
    AMMO,
    ARMOR,
    CANVAS,
    HEALTH,
    KILLS,
    MUTED,
    PANEL_FILL,
    TEXT,
    blend,
    gradient,
    text,
    wrap_text,
)

from symbiont.act1.hook_overlay import PAIN_LABELS, MoveCard, PlayerStats

GAME_AT, GAME_SIZE = (0, 56), (800, 600)
PANEL_X, PANEL_RIGHT = 816, 1264
MAP_RECT = (PANEL_X, 372, 190, 190)  # left, top, width, height
Point = tuple[float, float]
Segment = tuple[Point, Point]


@dataclass(frozen=True)
class StageFrame:
    """Everything one frame shows; `age` counts frames since its move started."""

    screen: np.ndarray
    card: MoveCard
    counts: dict[str, int]
    stats: PlayerStats
    events: motion.Events
    age: int
    frames_left: int
    decision: int
    cap: int
    said: str
    reasoning_chars: int
    model_seconds: float
    ammo_max: int
    trail: list[Point] = field(default_factory=list)
    marks: list[Point] = field(default_factory=list)


class StagePainter:
    """Draws `StageFrame`s; the level's wall segments give the mini-map its fixed frame."""

    def __init__(self, headline: str, walls: list[Segment]):
        self._headline, self._walls = headline, walls
        xs = [p[0] for wall in walls for p in wall]
        ys = [p[1] for wall in walls for p in wall]
        self._bounds = (min(xs), min(ys), max(xs), max(ys))
        self._draw: ImageDraw.ImageDraw

    def frame(self, frame: StageFrame) -> bytes:
        image = gradient().copy()
        game = Image.fromarray(np.moveaxis(frame.screen, 0, -1)).resize(GAME_SIZE, Image.BILINEAR)
        image.paste(game, GAME_AT)
        self._draw = ImageDraw.Draw(image)
        self._title()
        self._bubble(frame)
        self._now(frame)
        self._bars(frame)
        self._kills(frame)
        self._minimap(frame)
        self._pains(frame)
        self._banner(frame)
        self._progress(frame)
        return image.tobytes()

    def _title(self) -> None:
        text(self._draw, (24, 12), "ai-symbiont", 26, KILLS)
        text(self._draw, (190, 17), self._headline, 22, TEXT)

    def _bubble(self, frame: StageFrame) -> None:
        left, top, right, bottom = PANEL_X, 64, PANEL_RIGHT, 176
        self._draw.rounded_rectangle((left, top, right, bottom), 14, PANEL_FILL, ARMOR, 2)
        self._draw.polygon(
            [(left + 30, bottom), (left + 54, bottom), (left + 24, bottom + 14)], PANEL_FILL
        )
        text(self._draw, (left + 14, top + 8), "Glimmer said:", 15, MUTED)
        lines = [line for line in frame.said.splitlines() if line.strip()][:3]
        for row, line in enumerate(wrap_text(" ; ".join(lines), 34, 2)):
            text(self._draw, (left + 14, top + 28 + row * 28), line, 22)
        note = f"thought for {frame.model_seconds:.1f} s   reasoning text not logged"
        text(self._draw, (left + 14, bottom - 22), note, 13, MUTED)

    def _now(self, frame: StageFrame) -> None:
        shown = frame.frames_left <= motion.BANNER_FRAMES
        text(self._draw, (PANEL_X, 196), frame.card.move, 20, AMMO)
        lines = wrap_text(frame.card.outcome, 40, 2) if shown else ["playing..."]
        for row, line in enumerate(lines):
            text(self._draw, (PANEL_X, 222 + row * 20), line, 16, TEXT if shown else MUTED)

    def _bars(self, frame: StageFrame) -> None:
        stats = frame.stats
        pulse = motion.pulse_strength(frame.events.hurt)
        rows = (
            ("HEALTH", stats.health, 100, self._health_color(stats.health), pulse),
            ("ARMOR", stats.armor, 100, ARMOR, 0.0),
            ("AMMO", stats.ammo, frame.ammo_max, AMMO, 0.0),
        )
        for row, (label, value, maximum, color, throb) in enumerate(rows):
            self._bar(272 + row * 32, (label, value, maximum), color, throb)
        self._damage_floats(frame)

    @staticmethod
    def _health_color(health: int) -> tuple[int, int, int]:
        return HEALTH if health > 50 else AMMO if health > 25 else ALERT

    def _bar(self, top: int, reading: tuple[str, int, int], color, throb: float) -> None:
        label, value, maximum = reading
        x0, x1 = PANEL_X + 92, PANEL_RIGHT - 70
        text(self._draw, (PANEL_X, top + 2), label, 15, color)
        outline = blend(MUTED, ALERT, throb)
        self._draw.rounded_rectangle(
            (x0, top, x1, top + 22), 8, (20, 22, 40), outline, 2 + round(2 * throb)
        )
        width = round((x1 - x0 - 4) * motion.bar_fill(value, maximum))
        if width > 0:
            fill = blend(color, ALERT, throb)
            self._draw.rounded_rectangle((x0 + 2, top + 2, x0 + 2 + width, top + 20), 6, fill)
        text(self._draw, (x1 + 12, top - 2), str(value), 26, color)

    def _damage_floats(self, frame: StageFrame) -> None:
        taken = motion.float_progress(frame.events.taken)
        if taken is not None and frame.events.taken is not None:
            color = blend(ALERT, PANEL_FILL, taken)
            text(
                self._draw,
                (PANEL_RIGHT - 150, 266 - round(34 * taken)),
                f"-{frame.events.taken.amount}",
                30,
                color,
            )

    def _kills(self, frame: StageFrame) -> None:
        stats = frame.stats
        x = PANEL_X + 215
        text(self._draw, (x, 372), "KILLS", 16, KILLS)
        scale = motion.pop_scale(frame.events.kill)
        flash = blend(KILLS, TEXT, (scale - 1.0) * 2)
        size = round(78 * scale)
        text(self._draw, (x, 392 - round((size - 78) * 0.6)), str(stats.kills), size, flash)
        dealt = motion.float_progress(frame.events.dealt)
        if dealt is not None and frame.events.dealt is not None:
            color = blend(KILLS, PANEL_FILL, dealt)
            text(
                self._draw,
                (x + 110, 400 - round(40 * dealt)),
                f"+{frame.events.dealt.amount}",
                30,
                color,
            )
        rows = (
            f"damage dealt {stats.damage_dealt}",
            f"damage taken {stats.damage_taken}",
            f"items {stats.items}   secrets {stats.secrets}",
            "status: DEAD" if stats.dead else "status: alive",
        )
        for row, line in enumerate(rows):
            color = ALERT if stats.dead and row == len(rows) - 1 else MUTED
            text(self._draw, (x, 488 + row * 20), line, 15, color)

    def _to_map(self, point: Point) -> tuple[int, int]:
        left, top, width, height = MAP_RECT
        x0, y0, x1, y1 = self._bounds
        scale = min((width - 12) / (x1 - x0), (height - 12) / (y1 - y0))
        px = left + 6 + (point[0] - x0) * scale
        py = top + height - 6 - (point[1] - y0) * scale
        return round(px), round(py)

    def _minimap(self, frame: StageFrame) -> None:
        left, top, width, height = MAP_RECT
        self._draw.rounded_rectangle(
            (left, top, left + width, top + height), 10, (16, 18, 34), MUTED, 1
        )
        for a, b in self._walls:
            self._draw.line([self._to_map(a), self._to_map(b)], (70, 78, 112), 1)
        if len(frame.trail) > 1:
            self._draw.line([self._to_map(p) for p in frame.trail], HEALTH, 2)
        for mark in frame.marks:
            x, y = self._to_map(mark)
            self._draw.line([(x - 5, y - 5), (x + 5, y + 5)], ALERT, 3)
            self._draw.line([(x - 5, y + 5), (x + 5, y - 5)], ALERT, 3)
        if frame.trail:
            self._glow(self._to_map(frame.trail[-1]), frame.age)
        text(self._draw, (left + 8, top + height + 4), "path walked, X = mistake", 13, MUTED)

    def _glow(self, at: tuple[int, int], age: int) -> None:
        radius = 6 + round(2 * math.sin(age * 0.5))
        for grow, color in (
            (radius + 5, (60, 90, 130)),
            (radius + 2, (110, 170, 230)),
            (radius, TEXT),
        ):
            self._draw.ellipse((at[0] - grow, at[1] - grow, at[0] + grow, at[1] + grow), color)

    def _pains(self, frame: StageFrame) -> None:
        text(self._draw, (PANEL_X, 590), "PAIN POINTS (the real tagger)", 14, MUTED)
        for index, label in enumerate(PAIN_LABELS.values()):
            hot = frame.frames_left <= motion.BANNER_FRAMES and label in frame.card.pains
            x, y = PANEL_X + (index % 2) * 225, 612 + (index // 2) * 30
            text(
                self._draw,
                (x, y),
                f"{label}  {frame.counts.get(label, 0)}",
                20,
                ALERT if hot else TEXT,
            )

    def _banner(self, frame: StageFrame) -> None:
        if not frame.card.pains or not motion.banner_on(frame.frames_left):
            return
        flash = motion.banner_flash(frame.age)
        top = GAME_AT[1] + GAME_SIZE[1] - 96
        self._draw.rectangle((0, top, GAME_SIZE[0], top + 96), blend((20, 10, 14), ALERT, flash))
        label = "MISTAKE: " + " + ".join(frame.card.pains)
        text(self._draw, (28, top + 24), label.upper(), 44)

    def _progress(self, frame: StageFrame) -> None:
        text(self._draw, (24, 672), f"decision {frame.decision + 1} of {frame.cap}", 18, TEXT)
        x0, x1 = 230, 1256
        self._draw.rounded_rectangle((x0, 676, x1, 692), 6, (20, 22, 40), MUTED, 1)
        done = (frame.decision + 1) / frame.cap
        self._draw.rounded_rectangle((x0 + 1, 677, x0 + round((x1 - x0) * done), 691), 6, ARMOR)
        text(self._draw, (24, 698), "labels: the real tagger, nothing added by hand", 14, MUTED)


def title_card(headline: str, subline: str) -> bytes:
    """The opening card: what is playing, in plain words."""
    image = gradient().copy()
    draw = ImageDraw.Draw(image)
    text(draw, (80, 250), "ai-symbiont", 40, KILLS)
    text(draw, (80, 325), headline, 42)
    text(draw, (80, 410), subline, 28, MUTED)
    return image.tobytes()


__all__ = ["CANVAS", "StageFrame", "StagePainter", "title_card"]
