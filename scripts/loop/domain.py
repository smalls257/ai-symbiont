"""What a domain plugin gives the loop: tasks, attempts, harvest, marks, ablation, leak check.

The round runner knows six steps and nothing about sqlglot or Freedoom; a new domain is one new
plugin implementing `Domain`. The plugin owns what is domain-shaped (grading, when a lesson
applies, what counts as a leak) and returns only the loop's own types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from attempts import Attempt
from loop_cards import LessonCard
from training_plan import Row
from utility import AblationPair, Mark


class LessonLeakError(ValueError):
    """A lesson or row text carries a held-out task's answer (gold line, held-out level)."""


@dataclass(frozen=True)
class Harvest:
    """A round's harvest: new or newly closed cards, their situation rows, success rows.

    `unresolved` counts mistakes that no verified success got past yet (kept as open cards or,
    where the domain cannot word one, only counted).
    """

    cards: tuple[LessonCard, ...]
    situation_rows: Mapping[str, Sequence[Row]] = field(default_factory=dict)
    success_rows: tuple[Row, ...] = ()
    unresolved: int = 0


class Domain(Protocol):
    """One domain plugin. Every method raises on missing input; none returns a quiet empty."""

    name: str
    plain_model: str  # the router name of plain Glimmer (round 0 and the reference arm)
    subject: str  # how a row's question names the domain: "In sqlglot", "In Freedoom"
    memory_system: str  # the system turn card rows are trained under (and verify asks under)
    max_row_chars: int  # rows above this are dropped and counted by the train step

    def held_out(self) -> frozenset[str]:
        """The held-out task ids, declared before round 0; never mined."""
        ...

    def training_batch(self, round_index: int) -> tuple[str, ...]:
        """This round's training tasks (never a held-out one)."""
        ...

    def attempt(
        self, model: str, tasks: Sequence[str], round_index: int, trained: frozenset[str]
    ) -> list[Attempt]:
        """Run and grade `model` on training `tasks`; `trained` = lesson ids it learned."""
        ...

    def evaluate(self, model: str, round_index: int, trained: frozenset[str]) -> list[Attempt]:
        """Run and grade `model` on every held-out task."""
        ...

    def harvest(
        self,
        attempts: Sequence[Attempt],
        known: Mapping[str, LessonCard],
        quotas: Mapping[str, int],
    ) -> Harvest:
        """Cards from all graded training attempts so far; at most `quotas[kind]` new per kind."""
        ...

    def mark(self, card: LessonCard, attempt: Attempt) -> Mark:
        """Whether the card's situation arose in the attempt, and whether its mistake recurred."""
        ...

    def ablate(
        self, model: str, cards: Sequence[LessonCard], attempts: Sequence[Attempt]
    ) -> list[AblationPair]:
        """With/without-card pairs on a small sample where cheap; [] when the domain has none."""
        ...

    def leak_hits(self, texts: Mapping[str, str]) -> dict[str, list[str]]:
        """Every text (by key) that carries held-out answers, and what it carries."""
        ...
