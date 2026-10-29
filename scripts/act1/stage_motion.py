"""The video's motion rules as pure functions of a frame's age: what pops, pulses and fades.

Violation prevented: Paper Tiger in the visuals. Every animated number is driven by a real
game-counter change between two moves (kills went up, health went down), so nothing moves for
show; the functions take counters and an age and return a scale, alpha or offset. No pixels here.
"""

import math
from dataclasses import dataclass

from symbiont.act1.hook_overlay import PlayerStats

POP_FRAMES = 10  # a kill counter swells for about a third of a second at 30 fps
FLOAT_FRAMES = 36  # "+30" and "-12" rise and fade over about 1.2 s
PULSE_FRAMES = 30
BANNER_FRAMES = 30  # the mistake banner holds for 1 s


@dataclass(frozen=True)
class Event:
    """A counter change `age` frames ago of `amount`."""

    amount: int
    age: int


@dataclass(frozen=True)
class Events:
    """The recent counter changes the panel animates; None means nothing recent to show."""

    kill: Event | None = None
    hurt: Event | None = None
    dealt: Event | None = None
    taken: Event | None = None


class EventClock:
    """Turns successive frames' game counters into aged events (episode time, not move time).

    Prevents Paper Tiger in the visuals: an event exists only because a counter changed between
    two consecutive frames of the real game, and it fades on a fixed clock afterward.
    """

    def __init__(self) -> None:
        self._previous: PlayerStats | None = None
        self._frame = 0
        self._last: dict[str, tuple[int, int]] = {}

    def tick(self, stats: PlayerStats) -> Events:
        """Advance one frame; returns the events still within their animation window."""
        before = self._previous
        if before is not None:
            self._note("kill", stats.kills - before.kills)
            self._note("hurt", before.health - stats.health)
            self._note("dealt", stats.damage_dealt - before.damage_dealt)
            self._note("taken", stats.damage_taken - before.damage_taken)
        self._previous = stats
        self._frame += 1
        return Events(*(self._aged(name) for name in ("kill", "hurt", "dealt", "taken")))

    def _note(self, name: str, amount: int) -> None:
        if amount > 0:
            self._last[name] = (self._frame, amount)

    def _aged(self, name: str) -> Event | None:
        found = self._last.get(name)
        if found is None:
            return None
        age = self._frame - found[0] - 1
        return Event(found[1], age) if age < FLOAT_FRAMES else None


def pop_scale(kill: Event | None) -> float:
    """1.0 at rest; swells to 1.5 on the frame a kill lands and settles within POP_FRAMES."""
    if kill is None or kill.age >= POP_FRAMES:
        return 1.0
    return 1.0 + 0.5 * (1.0 - kill.age / POP_FRAMES)


def float_progress(event: Event | None) -> float | None:
    """0 to 1 over a floating number's life, None when there is nothing to show."""
    return None if event is None else event.age / FLOAT_FRAMES


def pulse_strength(hurt: Event | None) -> float:
    """0 to 1: a red throb on the health bar while the damage is fresh."""
    if hurt is None or hurt.age >= PULSE_FRAMES:
        return 0.0
    return (0.5 + 0.5 * math.sin(hurt.age * 0.9)) * (1.0 - hurt.age / PULSE_FRAMES)


def banner_on(frames_left: int) -> bool:
    """True for the last BANNER_FRAMES frames of a move that the real tagger flagged."""
    return frames_left <= BANNER_FRAMES


def banner_flash(age: int) -> float:
    """0.6 to 1.0, flickering so the banner reads as an alarm."""
    return 0.8 + 0.2 * math.sin(age * 1.2)


def bar_fill(value: int, maximum: int) -> float:
    """Fraction of a bar to fill, clamped to 0..1; raises ValueError for a non-positive maximum."""
    if maximum <= 0:
        raise ValueError(f"a bar needs a positive maximum, got {maximum}")
    return max(0.0, min(1.0, value / maximum))
