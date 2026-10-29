"""Lineage: where each card came from, recorded at birth (pure).

Reconstructing a winning lesson's ancestry after the fact means reading ruins; each birth is
recorded when it happens. The published form holds ids, generations, operators and rejection
labels, never lesson text.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from symbiont.act1.generality import Rejection


class Operator(StrEnum):
    """How a card came to be."""

    SEED_EMPTY = "seed_empty"
    SEED_HISTORY = "seed_history"
    SEED_SPARK = "seed_spark"
    REWRITE = "rewrite"
    ADD = "add"
    DELETE = "delete"
    MERGE = "merge"
    CROSSOVER = "crossover"
    ELITE = "elite"


class Arm(StrEnum):
    """Which population a card lives in."""

    EVOLVED = "evolved"
    NO_SELECTION = "no_selection"


class LineageError(ValueError):
    """A birth that contradicts its operator or names a parent that was never born."""


class UnknownCardError(LineageError):
    """A card with no accepted birth in the lineage."""


SEEDS = frozenset({Operator.SEED_EMPTY, Operator.SEED_HISTORY, Operator.SEED_SPARK})


@dataclass(frozen=True)
class Birth:
    """One card's birth. `rejection` is set when the generality filter turned the child away."""

    card_id: str
    generation: int
    arm: Arm
    operator: Operator
    parents: tuple[str, ...]
    author: str
    rejection: Rejection | None


def _expected_parents(operator: Operator) -> int:
    """Seeds have none, crossover two, every other operator one."""
    if operator in SEEDS:
        return 0
    return 2 if operator == Operator.CROSSOVER else 1


@dataclass
class Lineage:
    """All births in order; rejected children are listed but are never parents."""

    births: list[Birth] = field(default_factory=list)
    _origin: dict[str, Birth] = field(default_factory=dict, repr=False)

    def add(self, birth: Birth) -> None:
        """Record a birth. Raises LineageError for a wrong parent count or an unborn parent."""
        wanted = _expected_parents(birth.operator)
        if len(birth.parents) != wanted:
            raise LineageError(
                f"{birth.operator} takes {wanted} parent(s); card {birth.card_id} has "
                f"{len(birth.parents)}"
            )
        for parent in birth.parents:
            if parent not in self._origin:
                raise LineageError(f"parent {parent} of card {birth.card_id} has no accepted birth")
        self.births.append(birth)
        if birth.rejection is None and birth.operator != Operator.ELITE:
            self._origin.setdefault(birth.card_id, birth)

    def ancestors(self, card_id: str) -> list[Birth]:
        """The card's birth, then its parents' births and so on, nearest first, each once."""
        if card_id not in self._origin:
            raise UnknownCardError(f"card {card_id} has no accepted birth")
        found: list[Birth] = []
        queue = [card_id]
        while queue:
            current = queue.pop(0)
            if any(b.card_id == current for b in found):
                continue
            origin = self._origin[current]
            found.append(origin)
            queue.extend(origin.parents)
        return found

    def publishable(self) -> dict[str, Any]:
        """Ids, generations, operators and rejection labels: nothing a lesson says."""
        return {
            "births": [
                {
                    "card_id": b.card_id,
                    "generation": b.generation,
                    "arm": b.arm.value,
                    "operator": b.operator.value,
                    "parents": list(b.parents),
                    "author": b.author,
                    "rejection": None if b.rejection is None else b.rejection.value,
                }
                for b in self.births
            ]
        }
