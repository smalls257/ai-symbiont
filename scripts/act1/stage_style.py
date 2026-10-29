"""Colors, fonts and small drawing helpers shared by the video panel and the totals card.

Violation prevented: Forensic Coding in the video look. One accent color per stat lives here with
its reason, so a reader changing the panel does not hunt through draw calls for what orange means.
Periphery only (Pillow); the pure motion rules are in stage_motion.py.
"""

from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CANVAS = (1280, 720)
Color = tuple[int, int, int]
TEXT: Color = (240, 243, 250)
MUTED: Color = (150, 158, 180)
PANEL_FILL: Color = (34, 38, 66)
# One accent per stat: green health, blue armor, gold ammo, orange kills, red for anything the
# tagger or the damage counter calls bad. The pain banner and the "taken" number share the red.
HEALTH: Color = (84, 222, 124)
ARMOR: Color = (96, 164, 255)
AMMO: Color = (255, 204, 64)
KILLS: Color = (255, 128, 64)
ALERT: Color = (244, 72, 72)
BOLD_FONT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


@cache
def font(size: int) -> ImageFont.FreeTypeFont:
    """Arial Bold from macOS for crisp 720p type; the video is rendered on the owner's laptop.

    Raises FileNotFoundError when the font is missing rather than quietly drawing in another face.
    """
    if not BOLD_FONT.exists():
        raise FileNotFoundError(f"{BOLD_FONT} is not installed; the video look needs it")
    return ImageFont.truetype(str(BOLD_FONT), size)


@cache
def gradient(size: tuple[int, int] = CANVAS) -> Image.Image:
    """The subtle top-to-bottom background shared by the panel, title card and totals card."""
    top, bottom = np.array((12, 14, 30)), np.array((34, 18, 48))
    rows = np.linspace(top, bottom, size[1])[:, None, :].repeat(size[0], axis=1)
    return Image.fromarray(rows.astype(np.uint8))


def blend(color: Color, toward: Color, amount: float) -> Color:
    """`color` moved `amount` (0 to 1) of the way to `toward`; fades a number into the panel."""
    red, green, blue = (round(c + (t - c) * amount) for c, t in zip(color, toward, strict=True))
    return (red, green, blue)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], words: str, size: int, color=TEXT) -> None:
    draw.text(xy, words, font=font(size), fill=color)


def wrap_text(words: str, chars: int, max_lines: int) -> list[str]:
    """Greedy wrap to `chars` per line; overflow past `max_lines` ends in an ellipsis."""
    lines: list[str] = []
    line = ""
    for word in words.split():
        if line and len(line) + 1 + len(word) > chars:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    if len(lines) > max_lines:
        lines = [*lines[: max_lines - 1], " ".join(lines[max_lines - 1 :])]
    return [entry if len(entry) <= chars else entry[: chars - 1] + "…" for entry in lines]
