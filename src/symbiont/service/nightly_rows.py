"""The night's training rows from a repository's lessons: plug round 4's nightly recipe.

Each lesson is asked in several situations (yes) against another lesson of the repository (no),
balanced; general judge rows make up 25% and habit rows 15% of the result. Unlike the measured arm
[hypothesis], which had a remote model invent 12 situations per lesson and label extra pairs,
this makes no network call: situations are the fixed `PHRASINGS` rewordings and no teacher
labels are added.
"""

import math
import random
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.judge_format import (
    JUDGE_SYSTEM,
    NO_FILE,
    JudgeableLesson,
    judge_input,
    judge_input_text,
    judge_lesson_text,
    judge_situation,
    judgeable,
)
from symbiont.miner.lessons import Lesson

SHORTLIST = 10  # plug_r4.SHORTLIST: hard negatives come from the ranker's top ten
REPLAY_SHARE = 0.25  # plug_r4_cont.REPLAY_SHARE: general judge rows in the mixed result
HABIT_SHARE = 0.15  # the nightly arm's habit replay (prereg amendment: 15%)
SEED = 0
YES, NO = "yes", "no"
ChatRow = dict[str, list[dict[str, str]]]  # {"messages": [system, user, assistant]}
# plug_r2_rows.PHRASINGS, fixed before round 2 ran: the situation reworded without new facts.
PHRASINGS = (
    "Command `{failed}` just failed in {repo} while working on {file}: {error}",
    "In {repo}, running `{failed}` (touching {file}) gave: {error}",
    "The agent ran `{failed}` for {file} in {repo} and saw: {error}",
    "{repo}: `{failed}` failed. File: {file}. Error: {error}",
    "Working in {repo} on {file}. Last command `{failed}` returned an error: {error}",
    "Error from `{failed}` in {repo} ({file}): {error}",
    "While editing {file} in {repo}, `{failed}` stopped with: {error}",
    "Repo {repo}, file {file}: the command `{failed}` failed with {error}",
    "`{failed}` did not work in {repo}; it reported {error} (file {file})",
    "Just tried `{failed}` in {repo} for {file}. Output: {error}",
    "The run of `{failed}` on {file} in {repo} ended in an error: {error}",
    "{error}, after running `{failed}` in {repo} on {file}",
    "In the {repo} checkout, `{failed}` failed for {file} with {error}",
    "Attempted `{failed}` ({repo}, {file}); result: {error}",
)
PHRASINGS_PER_LESSON = 6
_WORD = re.compile(r"[A-Za-z_][\w.\-/]+")
_LESSON_TEXT = re.compile(r"\n\nLesson:\n(.*)\n\nDoes this lesson apply\?", re.DOTALL)


class NoUsableLessonsError(ValueError):
    """The store has lessons, but none has a failed command and a fix for the judge to learn."""


@dataclass(frozen=True)
class Trainable:
    """A stored lesson in the judge's fields, with the file its failure happened in."""

    lesson: JudgeableLesson
    file: str

    def situation(self) -> str:
        """The failure as the service words it when it asks the judge."""
        return judge_situation(self.lesson.failed, self.lesson.repo, self.file, self.lesson.error)

    def reworded(self, template: str) -> str:
        """The same failure in one of the fixed rewordings."""
        return template.format(
            failed=self.lesson.failed,
            repo=self.lesson.repo,
            file=self.file,
            error=self.lesson.error,
        )


def trainable_lessons(lessons: Sequence[Lesson], project: str) -> list[Trainable]:
    """The lessons the judge can learn from; the others (no failed command or no fix) are left out.

    Raises NoUsableLessonsError when lessons exist but none qualifies, so the caller never trains
    on rows that carry no lesson.
    """
    found = [(lesson, judgeable(lesson, project)) for lesson in lessons]
    kept = [
        Trainable(read, lesson.files[0] if lesson.files else NO_FILE)
        for lesson, read in found
        if read
    ]
    if lessons and not kept:
        raise NoUsableLessonsError(
            f"none of the {len(lessons)} lessons has both a failed command and a fix command"
        )
    return kept


def night_rows(
    items: Sequence[Trainable],
    general: Sequence[ChatRow],
    habits: Sequence[ChatRow],
    seed: int = SEED,
) -> list[ChatRow]:
    """One repository's training rows: its lessons, general judge replay, then habit replay."""
    own = _own_rows(items, _foreign_texts(general), seed)
    mixed = with_replay(_balanced(own, seed), general, REPLAY_SHARE, seed)
    return with_habits(mixed, habits, seed)


def _own_rows(items: Sequence[Trainable], foreign: Sequence[str], seed: int) -> list[ChatRow]:
    """A yes row and a no row per situation of every lesson."""
    rng = random.Random(seed)
    rows: list[ChatRow] = []
    for item in items:
        others = [judge_lesson_text(x) for x in _hard_negatives(item, items)] or list(foreign)
        for situation in _situations(item, rng):
            rows.append(_row(judge_input(situation, item.lesson), YES))
            if others:
                rows.append(_row(judge_input_text(situation, rng.choice(others)), NO))
    rng.shuffle(rows)
    return rows


def _situations(item: Trainable, rng: random.Random) -> list[str]:
    """The lesson's own situation and a seeded few of the fixed rewordings."""
    chosen = rng.sample(PHRASINGS, PHRASINGS_PER_LESSON)
    return [item.situation(), *(item.reworded(template) for template in chosen)]


def _hard_negatives(item: Trainable, items: Sequence[Trainable]) -> list[JudgeableLesson]:
    """The ranker's top lessons that are not this one: what the judge must tell apart from it."""
    scores = lexical_scores(item.situation(), [other.lesson for other in items])
    ranked = sorted(items, key=lambda other: (-scores[id(other.lesson)], other.lesson.fix))
    same_failure = (item.lesson.failed, item.lesson.error)
    return [
        other.lesson
        for other in ranked[:SHORTLIST]
        if (other.lesson.failed, other.lesson.error) != same_failure
    ]


def words(text: str) -> set[str]:
    """Lower-case identifiers, paths and command words (plug_situation.words)."""
    return set(_WORD.findall(text.lower()))


def lexical_scores(situation: str, lessons: Sequence[JudgeableLesson]) -> dict[int, float]:
    """Inverse-document-frequency overlap of each lesson with the situation, keyed by `id()`.

    Same ranker as plug_situation.lexical_scores, over the fields the product lesson has.
    """
    docs = {id(x): words(f"{x.repo} {x.failed} {x.error}") for x in lessons}
    spread = Counter(word for doc in docs.values() for word in doc)
    mine = words(situation)
    return {
        key: sum(math.log(len(docs) / spread[w]) for w in doc & mine) for key, doc in docs.items()
    }


def _row(user: str, answer: str) -> ChatRow:
    """One chat training row in the judge's layout."""
    return {
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ]
    }


def _foreign_texts(general: Sequence[ChatRow]) -> list[str]:
    """Lesson texts of other repositories, read from the general rows.

    They are the negatives for a repository with only one lesson of its own. A row that does not
    carry a lesson is skipped: general rows are replay, not evidence.
    """
    found = (_LESSON_TEXT.search(row["messages"][1]["content"]) for row in general)
    return sorted({match.group(1) for match in found if match})


def _balanced(rows: list[ChatRow], seed: int) -> list[ChatRow]:
    """Yes and no rows in equal number: the larger side is sampled down, seeded."""
    yes = [r for r in rows if r["messages"][2]["content"] == YES]
    no = [r for r in rows if r["messages"][2]["content"] == NO]
    size = min(len(yes), len(no))
    rng = random.Random(seed)
    kept = rng.sample(yes, size) + rng.sample(no, size)
    rng.shuffle(kept)
    return kept


def with_replay(
    rows: list[ChatRow], general: Sequence[ChatRow], share: float, seed: int = SEED
) -> list[ChatRow]:
    """The rows plus general rows making up `share` of the total (plug_r4_cont.with_replay)."""
    needed = round(len(rows) * share / (1 - share))
    rng = random.Random(seed)
    mixed = rows + rng.sample(list(general), min(needed, len(general)))
    rng.shuffle(mixed)
    return mixed


def with_habits(rows: list[ChatRow], habits: Sequence[ChatRow], seed: int = SEED) -> list[ChatRow]:
    """The rows plus habit rows, sampled with replacement, making up HABIT_SHARE of the total."""
    needed = round(len(rows) * HABIT_SHARE / (1 - HABIT_SHARE))
    rng = random.Random(seed)
    mixed = rows + [rng.choice(habits) for _ in range(needed)]
    rng.shuffle(mixed)
    return mixed
