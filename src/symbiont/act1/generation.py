"""One generation for one arm: elites stay, children are written, rejected children are replaced.

The two arms run this same function and differ only in the named parent choice, so they cannot
drift apart. Every rule it applies lives in another module (lexicase, generality, run_guards,
card_archive); this one only sequences them.
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from symbiont.act1.card_genome import MAX_LESSONS, MAX_WORDS, Card, Lesson
from symbiont.act1.game_fitness import GameResult
from symbiont.act1.generality import Verdict, check_lesson
from symbiont.act1.lexicase import FitnessTable, elites, random_parents, select_parents
from symbiont.act1.lineage import Arm, Birth, Operator
from symbiont.act1.run_guards import MutationPromptError, require_rejection_share

ELITES = 2  # design section 4: the two best survive
CHILDREN = 4  # six cards: two elites and four children
REDRAWS = 5  # a crossover of a card with itself is a copy: redraw this many times for two cards
MAX_COPIES = 6  # a child equal to a card already kept is not a rejection; it has its own budget
MAX_TRIES = 3  # plan T13: a rejected child is replaced at most three times per slot
VARIATION_OPERATORS = (
    Operator.REWRITE,
    Operator.ADD,
    Operator.DELETE,
    Operator.MERGE,
    Operator.CROSSOVER,
)


class MutationReplyError(ValueError):
    """An author reply that is not a valid card."""


class ParentChoice(StrEnum):
    """How parents are drawn: the only difference between the arms."""

    LEXICASE = "lexicase"
    RANDOM = "random"


class Author(Protocol):
    """Writes a child card. Raises MutationReplyError for a reply that is not one."""

    name: str

    def vary(self, operator: Operator, parents: tuple[Card, ...], summary: str) -> Card:
        """A child of the parents by the operator."""
        ...


class Judge(Protocol):
    """Rejects a lesson that describes a landmark (plan T19)."""

    def landmark(self, lesson: Lesson) -> Verdict:
        """General, or a LANDMARK rejection."""
        ...


@dataclass(frozen=True)
class OperatorSchedule:
    """Which operator writes each child, the same for both arms (plan ruling 6).

    A shuffled round of the five operators per generation gives equal shares; a replacement
    attempt moves on in the round.
    """

    seed: int

    def operator(self, generation: int, slot: int, attempt: int) -> Operator:
        """The operator for a child slot and attempt."""
        order = list(VARIATION_OPERATORS)
        random.Random(f"{self.seed}:{generation}").shuffle(order)
        return order[(slot + attempt * CHILDREN) % len(order)]


@dataclass(frozen=True)
class Population:
    """The cards of one arm in one generation."""

    generation: int
    arm: Arm
    cards: tuple[Card, ...]


@dataclass(frozen=True)
class VariationTools:
    """What variation needs: who writes, who judges, chance, the schedule and card summaries."""

    author: Author
    judge: Judge
    rng: random.Random
    schedule: OperatorSchedule
    summaries: Mapping[str, str]


@dataclass(frozen=True)
class Step:
    """The next population and everything the run records about getting there."""

    population: Population
    births: tuple[Birth, ...]
    table: FitnessTable
    archive_offers: tuple[tuple[Card, float], ...]
    verdicts: tuple[Verdict, ...]
    duplicates: int


def crossover(first: Card, second: Card) -> Card:
    """The first half of one parent's lessons and the second half of the other's, within caps.

    Pure code, no author call; lessons are dropped from the end until the card fits.
    """
    head = first.lessons[: math.ceil(len(first.lessons) / 2)]
    tail = second.lessons[len(second.lessons) // 2 :]
    lessons = list(dict.fromkeys([*head, *tail]))[:MAX_LESSONS]
    while sum(lesson.words() for lesson in lessons) > MAX_WORDS:
        lessons.pop()
    return Card.of(lessons)


def _new_lessons(child: Card, parents: Sequence[Card]) -> list[Lesson]:
    """Lessons of the child that no parent had: only these are filtered and judged."""
    known = {lesson for parent in parents for lesson in parent.lessons}
    return [lesson for lesson in child.lessons if lesson not in known]


def _verdict_on(child: Card, parents: Sequence[Card], judge: Judge) -> Verdict:
    """The first rejection among the child's new lessons (patterns, then the judge)."""
    for lesson in _new_lessons(child, parents):
        verdict = check_lesson(lesson)
        if verdict.general:
            verdict = judge.landmark(lesson)
        if not verdict.general:
            return verdict
    return Verdict(general=True, rejection=None, evidence="")


@dataclass
class _Run:
    """Mutable bookkeeping of one next_population call."""

    population: Population
    choice: ParentChoice
    tools: VariationTools
    table: FitnessTable
    by_id: dict[str, Card]
    births: list[Birth]
    verdicts: list[Verdict]
    taken: set[str]
    duplicates: int = 0

    def tie_key(self, card_id: str) -> tuple[int, str]:
        """Shorter wins, then id, for the card with this id."""
        return self.by_id[card_id].tie_key()

    def draw_parents(self, count: int) -> tuple[Card, ...]:
        """Parents by the arm's named choice; a crossover redraws to get two different cards."""
        for _ in range(REDRAWS):
            ids = self._draw_ids(count)
            if len(set(ids)) == count:
                break
        return tuple(self.by_id[card_id] for card_id in ids)

    def _draw_ids(self, count: int) -> tuple[str, ...]:
        """One draw of `count` parent ids by the named choice."""
        if self.choice == ParentChoice.RANDOM:
            return random_parents(self.table.cards, count, self.tools.rng)
        return select_parents(self.table, count, self.tools.rng, self.tie_key)

    def write_child(self, operator: Operator, parents: tuple[Card, ...]) -> Card:
        """Crossover by code; every other operator through the author."""
        if operator == Operator.CROSSOVER:
            return crossover(parents[0], parents[1])
        summary = self.tools.summaries[parents[0].card_id]
        return self.tools.author.vary(operator, parents[:1], summary)

    def record(
        self, child: Card, operator: Operator, parents: tuple[Card, ...], why: Verdict
    ) -> None:
        """Log the child's birth, with the rejection label if it was turned away."""
        self.births.append(
            Birth(
                child.card_id,
                self.population.generation + 1,
                self.population.arm,
                operator,
                tuple(parent.card_id for parent in parents),
                self.tools.author.name,
                why.rejection,
            )
        )
        self.verdicts.append(why)


def _fill_slot(run: _Run, slot: int) -> Card:
    """Write one child; replace a rejected one up to MAX_TRIES times and a copy up to MAX_COPIES.

    Raises MutationPromptError when either budget runs out.
    """
    generation = run.population.generation + 1
    rejected = copies = 0
    for attempt in range(MAX_TRIES + MAX_COPIES):
        operator = run.tools.schedule.operator(generation, slot, attempt)
        parents = run.draw_parents(2 if operator == Operator.CROSSOVER else 1)
        child = run.write_child(operator, parents)
        if child.card_id in run.taken:
            run.duplicates, copies = run.duplicates + 1, copies + 1
        else:
            why = _verdict_on(child, parents, run.tools.judge)
            run.record(child, operator, parents, why)
            if why.general:
                return child
            rejected += 1
        if rejected >= MAX_TRIES:
            break
    raise MutationPromptError(
        f"slot {slot}: no new general child after {rejected} rejections and {copies} copies"
    )


def next_population(
    population: Population,
    results: Sequence[GameResult],
    choice: ParentChoice,
    tools: VariationTools,
) -> Step:
    """Two elites by mean fitness plus four children by the arm's parent choice.

    Raises MutationPromptError when a slot finds no general child or more than half of the
    generation's children were rejected, and MutationReplyError from the author.
    """
    table = FitnessTable.of(results)
    by_id = {card.card_id: card for card in population.cards}
    run = _Run(population, choice, tools, table, by_id, [], [], set(by_id))
    kept = elites(table, ELITES, run.tie_key)
    run.births.extend(_elite_birth(population, card_id) for card_id in kept)
    children = []
    for slot in range(CHILDREN):
        child = _fill_slot(run, slot)
        run.taken.add(child.card_id)
        children.append(child)
    require_rejection_share(run.verdicts)
    cards = (*(by_id[card_id] for card_id in kept), *children)
    return Step(
        Population(population.generation + 1, population.arm, cards),
        tuple(run.births),
        table,
        archive_offers(table, by_id),
        tuple(run.verdicts),
        run.duplicates,
    )


def _elite_birth(population: Population, card_id: str) -> Birth:
    """An elite carried into the next generation."""
    return Birth(
        card_id, population.generation + 1, population.arm, Operator.ELITE, (card_id,),
        "code", None,
    )  # fmt: skip


def archive_offers(
    table: FitnessTable, by_id: Mapping[str, Card]
) -> tuple[tuple[Card, float], ...]:
    """Every card of the table with its mean fitness, for the niche archive."""
    offers = []
    for card_id in table.cards:
        scores = [table.scores[(card_id, case)] for case in table.cases]
        offers.append((by_id[card_id], sum(scores) / len(scores)))
    return tuple(offers)
