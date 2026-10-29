"""A loop lesson card: what went wrong, how a verified success got past it, the check to run.

A resolution comes only with its proof (`Resolution`: own verified success, an upstream fix of a
training task, or progress the game engine observed); anything else raises
`UnverifiedResolutionError`, so an unverified guess is never trained as a fix. An open card
teaches the mistake and the check only. Cards are kept lesson text, never raw history. Pure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ResolutionSource(StrEnum):
    """What proves that the recorded resolution really got past the mistake."""

    OWN_VERIFIED_SUCCESS = "own verified success"  # a graded pass or a reached exit, own attempt
    UPSTREAM_FIX = "upstream fix"  # coding: the merged fix of a training task, never a held-out one
    ENGINE_PROGRESS = "engine-observed progress"  # game: the engine saw the move reach a new room


class UnverifiedResolutionError(ValueError):
    """A card was given a resolution without proof, or proof without a resolution."""


@dataclass(frozen=True)
class Resolution:
    """The proof behind a card's "how it was resolved": its source and the ids that show it."""

    source: ResolutionSource
    evidence: tuple[str, ...]  # attempt ids or training task ids; never empty

    def __post_init__(self) -> None:
        """Proof with no evidence is no proof."""
        if not self.evidence:
            raise UnverifiedResolutionError(f"a {self.source} resolution needs evidence ids")


@dataclass(frozen=True)
class LessonCard:
    """One kept lesson in the three-part form, with where it came from.

    `kind` names the harvest rule that made the card; lesson utility is judged per card and per
    kind, so the loop learns which rules make lessons that help. `first_round` is the round whose
    attempts the card was harvested from.
    """

    lesson_id: str
    domain: str
    kind: str
    situation: str  # when the lesson applies, second person
    what_happened: str
    check: str
    source_tasks: tuple[str, ...]
    first_round: int
    resolution: Resolution | None = None
    how_resolved: str = ""

    def __post_init__(self) -> None:
        """A resolution text and its proof come together or not at all."""
        if bool(self.how_resolved.strip()) != (self.resolution is not None):
            raise UnverifiedResolutionError(
                f"{self.lesson_id}: 'how it was resolved' needs a verified resolution and the "
                "reverse; an open card leaves both empty"
            )

    @property
    def is_open(self) -> bool:
        """No verified resolution yet: the card teaches the mistake and the check only."""
        return self.resolution is None

    def text(self) -> str:
        """The card as Glimmer reads it; every trained card opens with "What happened:"."""
        resolved = "" if self.is_open else f" How it was resolved: {self.how_resolved}"
        return f"What happened: {self.what_happened}{resolved} The check to run: {self.check}"

    def resolved_by(self, resolution: Resolution, how_resolved: str) -> LessonCard:
        """The same card, now closed by a verified resolution (a later round's success)."""
        return LessonCard(
            **{**self.__dict__, "resolution": resolution, "how_resolved": how_resolved}
        )

    def to_json(self) -> dict[str, Any]:
        """The card for the loop's local state file (text included; never committed)."""
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> LessonCard:
        """Inverse of `to_json`; a stored resolution without evidence raises."""
        found = raw.get("resolution")
        resolution = (
            Resolution(ResolutionSource(found["source"]), tuple(found["evidence"]))
            if found
            else None
        )
        fields = {**raw, "source_tasks": tuple(raw["source_tasks"]), "resolution": resolution}
        return cls(**fields)
