"""Paints a replayed episode's frames with the stage panel and notes which decision each belongs to.

A move whose game counters cannot be read stops the render (the counters come from ViZDoom, never
defaulted), and each decision's frame span is written down so side-by-side clips sync by decision.
"""

from dataclasses import dataclass
from typing import Any

import stage_motion as motion
from hook_video import ClipSink
from stage_panel import Point, StageFrame, StagePainter

from symbiont.act1.engine import read_player_stats, stats_from_variables
from symbiont.act1.episode import Decision
from symbiont.act1.frame_tap import FrameTap
from symbiont.act1.game_pains import tag_pains
from symbiont.act1.hook_overlay import MoveCard, card_for, tally

AMMO_BAR_MAX = 200  # Freedoom's bullet cap without a backpack; the bar shows ammo against it
DECISION_CAP = 16


@dataclass(frozen=True)
class ClipOutput:
    """Where the frames go and who paints them."""

    sink: ClipSink
    painter: StagePainter


class SegmentRecorder:
    """The observer `run_episode` calls after each move, painting and writing its frames."""

    def __init__(self, tap: FrameTap, rooms: Any, output: ClipOutput, logged: list[Decision]):
        self._tap, self._rooms, self._logged = tap, rooms, logged
        self._sink, self._painter = output.sink, output.painter
        self.runs: list[Any] = []
        self.cards: list[MoveCard] = []
        self.calls: list[int] = []
        self.last_stats: Any = None
        self.spans: dict[int, dict[str, Any]] = {}
        self._trail: list[Point] = []
        self._marks: list[Point] = []
        self._clock = motion.EventClock()

    @property
    def path_ends(self) -> tuple[Point, Point]:
        """First and last position seen; raises IndexError when no frame was ever kept."""
        return self._trail[0], self._trail[-1]

    def on_move(self, run: Any) -> None:
        self.runs.append(run)
        self.last_stats = read_player_stats(self._tap)
        pains = tag_pains(self.runs, self._rooms)[-1]
        card = card_for(len(self.runs) - 1, run, pains, self.last_stats)
        self.cards.append(card)
        frames, variables = self._tap.take_frames(), self._tap.take_variables()
        span = self.spans.setdefault(
            len(self.calls) - 1, {"first_frame": self._sink.frames, "end_frame": 0, "tally": {}}
        )
        shared = self._shared(card)
        positions = [(values[2], values[3]) for values in variables]
        marks = [*self._marks, positions[-1]] if card.pains and positions else self._marks
        for number, screen in enumerate(frames):
            stats = stats_from_variables(variables[number])
            frame = StageFrame(
                screen, stats=stats, events=self._clock.tick(stats), age=number,
                frames_left=len(frames) - number, trail=[*self._trail, *positions[: number + 1]],
                marks=marks, **shared,
            )  # fmt: skip
            self._sink.add(self._painter.frame(frame))
        self._trail.extend(positions)
        self._marks = marks
        span["end_frame"], span["tally"] = self._sink.frames, shared["counts"]

    def _shared(self, card: MoveCard) -> dict[str, Any]:
        """The fields every frame of this move shares; all from the log, counters or the tagger."""
        logged = self._logged[len(self.calls) - 1]
        return {
            "card": card, "counts": dict(tally(self.cards)),
            "decision": logged.index, "cap": DECISION_CAP, "said": logged.reply,
            "reasoning_chars": logged.reasoning_chars, "model_seconds": logged.model_seconds,
            "ammo_max": AMMO_BAR_MAX,
        }  # fmt: skip
