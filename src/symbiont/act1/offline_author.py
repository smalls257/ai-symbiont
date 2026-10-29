"""A lesson author and judge that call no model: deterministic text edits for dry runs (pure).

The dry run needs variation that is reproducible and free. Each edit is a function of the
operator and the parents alone (no counters), so two arms that ask the same question get the same
answer.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.act1.card_genome import MAX_LESSONS, Card, Lesson
from symbiont.act1.generality import Rejection, Verdict
from symbiont.act1.generation import MutationReplyError
from symbiont.act1.lineage import Operator

# Small pool of general lessons the offline author draws from; wording is test-grade prose.
OFFLINE_LESSONS = (
    Lesson(
        "Turned in a room that was already checked",
        "Walk through the nearest door instead",
        "Does the view show a door or exit not yet visited?",
    ),
    Lesson(
        "Fired with no enemy in view",
        "Shoot only at an enemy you can see",
        "Is an enemy in view right now?",
    ),
    Lesson(
        "Walked into a wall again and again",
        "Use go_to so the route goes around walls",
        "Did the last walk end against a wall?",
    ),
    Lesson(
        "Passed a locked door without a key",
        "Find the key of that color first",
        "Is the key held before the door is tried?",
    ),
    Lesson(
        "Went back to a room already left",
        "Head for a door not used yet",
        "Is this room new?",
    ),
)


QUALIFIERS = (
    "now", "before anything else", "carefully", "every time",
    "without waiting", "first", "at once", "calmly",
)  # fmt: skip


def _pick(text: str) -> Lesson:
    """A pool lesson with a qualifier, chosen by the hash of a text (same text, same lesson).

    Five bases times eight qualifiers keep two different parents from writing the same child.
    """
    digest = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    base = OFFLINE_LESSONS[digest % len(OFFLINE_LESSONS)]
    qualifier = QUALIFIERS[(digest // len(OFFLINE_LESSONS)) % len(QUALIFIERS)]
    return Lesson(base.went_wrong, f"{base.instead}, {qualifier}", base.check, base.source_level)


def _without_repeats(lessons: Sequence[Lesson]) -> list[Lesson]:
    """Drop later copies of a lesson, keeping order."""
    return list(dict.fromkeys(lessons))


# Below this size a delete or merge would collapse into the other small cards of the population.
SHRINKABLE_ABOVE = 2
PICK_TRIES = 12  # of 40 pool lessons a card holds at most 8, so a new one turns up quickly


def _new_pick(text: str, held: list[Lesson]) -> Lesson:
    """A pool lesson the card does not hold yet (the first of a few salted picks that is new)."""
    for salt in range(PICK_TRIES):
        lesson = _pick(f"{text}/{salt}")
        if lesson not in held:
            return lesson
    return _pick(text)


def _slot(text: str, size: int) -> int:
    """A stable index below `size` from a text."""
    return int(hashlib.sha256(text.encode()).hexdigest(), 16) % size


def _add(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Add the pool lesson the card and summary hash to; at the cap it replaces the last lesson."""
    text = "".join(lesson.went_wrong for lesson in lessons) + summary
    room = lessons[: MAX_LESSONS - 1] if len(lessons) >= MAX_LESSONS else lessons
    return [*room, _new_pick(text, room)]


def _delete(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Drop the lesson the summary hashes to; a card of two or fewer gets an addition instead."""
    if len(lessons) <= SHRINKABLE_ABOVE:
        return _add(lessons, summary)
    gone = _slot(summary, len(lessons))
    return [lesson for index, lesson in enumerate(lessons) if index != gone]


def _merge(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Merge a hashed neighbor pair into one lesson; a card of two or fewer gets an addition."""
    if len(lessons) <= SHRINKABLE_ABOVE:
        return _add(lessons, summary)
    at = _slot(summary, len(lessons) - 1)
    first, second = lessons[at], lessons[at + 1]
    merged = Lesson(first.went_wrong, first.instead, second.check, first.source_level)
    return [*lessons[:at], merged, *lessons[at + 2 :]]


def _rewrite(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Replace a hashed lesson by a pool lesson; an empty card gets an addition instead."""
    if not lessons:
        return _add(lessons, summary)
    at = _slot(summary, len(lessons))
    return _without_repeats(
        [*lessons[:at], _pick(lessons[at].went_wrong + summary), *lessons[at + 1 :]]
    )


EDITS = {
    Operator.ADD: _add,
    Operator.COMPARE: _add,
    Operator.DELETE: _delete,
    Operator.MERGE: _merge,
    Operator.REWRITE: _rewrite,
}


class OfflineAuthor:
    """Edits a parent card by operator. Never a model, and a pure function of its arguments.

    The per-call seed goes into the hash, so repeated asks about one parent (different attempts)
    give different children while both arms, asking with the same seed, get the same child. An
    edit that would collapse a tiny card adds a lesson instead, so a dry run does not burn its
    tries on copies.
    """

    name = "offline"

    def vary(self, operator: Operator, parents: tuple[Card, ...], summary: str, seed: int) -> Card:
        """A child of one parent; raises MutationReplyError for an operator it cannot do."""
        edit = EDITS.get(operator)
        if edit is None:
            raise MutationReplyError(f"offline author cannot do {operator}")
        return Card.of(edit(list(parents[0].lessons), f"{summary}#{seed}")[:MAX_LESSONS])


@dataclass(frozen=True)
class AllowAllJudge:
    """A judge that finds no landmark: only the pattern filter judges in a dry run."""

    def landmark(self, lesson: Lesson) -> Verdict:
        """Always general."""
        return Verdict(general=True, rejection=None, evidence="")


@dataclass(frozen=True)
class FlagWordJudge:
    """A judge that calls a lesson a landmark when it holds a given word (for tests)."""

    word: str

    def landmark(self, lesson: Lesson) -> Verdict:
        """LANDMARK when the word appears in any part."""
        text = f"{lesson.went_wrong} {lesson.instead} {lesson.check}".lower()
        if self.word.lower() in text:
            return Verdict(general=False, rejection=Rejection.LANDMARK, evidence=self.word)
        return Verdict(general=True, rejection=None, evidence="")
