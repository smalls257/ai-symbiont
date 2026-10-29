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


def _add(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Add the pool lesson chosen by the hash of the card and the summary."""
    text = "".join(lesson.went_wrong for lesson in lessons) + summary
    return _without_repeats([*lessons, _pick(text)])


def _delete(lessons: list[Lesson], _summary: str) -> list[Lesson]:
    """Drop the last lesson; an empty card stays empty."""
    return lessons[:-1]


def _merge(lessons: list[Lesson], _summary: str) -> list[Lesson]:
    """Merge the first two lessons into one; fewer than two stay as they are."""
    if len(lessons) < 2:
        return lessons
    first, second = lessons[0], lessons[1]
    merged = Lesson(first.went_wrong, first.instead, second.check, first.source_level)
    return [merged, *lessons[2:]]


def _rewrite(lessons: list[Lesson], summary: str) -> list[Lesson]:
    """Replace the first lesson by the pool lesson its problem hashes to."""
    if not lessons:
        return lessons
    return _without_repeats([_pick(lessons[0].went_wrong + summary), *lessons[1:]])


EDITS = {
    Operator.ADD: _add,
    Operator.DELETE: _delete,
    Operator.MERGE: _merge,
    Operator.REWRITE: _rewrite,
}


class OfflineAuthor:
    """Edits a parent card by operator. Never a model.

    A call counter goes into the hash so repeated asks about one parent give different children,
    as a sampling model would. A no-op edit (delete on an empty card) returns the parent's lessons.
    Give each arm its own copy so the counters start equal.
    """

    name = "offline"

    def __init__(self) -> None:
        """Start with no calls made."""
        self.calls = 0

    def vary(self, operator: Operator, parents: tuple[Card, ...], summary: str) -> Card:
        """A child of one parent; raises MutationReplyError for an operator it cannot do."""
        edit = EDITS.get(operator)
        if edit is None:
            raise MutationReplyError(f"offline author cannot do {operator}")
        self.calls += 1
        return Card.of(edit(list(parents[0].lessons), f"{summary}#{self.calls}")[:MAX_LESSONS])


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
