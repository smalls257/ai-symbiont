"""Plug situation test: an agent's current situation and many lessons; pick, note, or stay silent.

Each lesson gives a pick item (its situation, PROMPT_LESSONS lessons including it) and a silence
item (the same prompt without it). Distractors never share the lesson's failure key; the ranker's
top lessons are shuffled per item so their order gives nothing away. Scoring is whole-token
containment of a fix, excusing lessons the right note itself names, plus abstention.
"""

import math
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug import abstains, fold  # noqa: E402
from questions import lessons_prompt  # noqa: E402

PROMPT_LESSONS = 60  # within the 50-100 range the owner set; fits the 1B context at ~5k tokens
_EDGE = ".,;:!?()[]{}<>"  # punctuation stripped from token edges before whole-token matching
ASK = (
    "The agent is now doing this:\n{situation}\n"
    "Write one note for the agent, or say that no lesson applies."
)


@dataclass(frozen=True)
class Item:
    """A situation, the lessons in its prompt, and the lesson that applies, if any."""

    item_id: str
    situation: str
    prompt_lessons: tuple[Lesson, ...]
    applies: Lesson | None
    excused: tuple[str, ...] = ()  # lessons the applicable note itself names: never a wrong pick


def situation_of(lesson: Lesson) -> str:
    """What the agent is doing now, in the lesson's own short fields."""
    return f"Ran `{lesson.failed}` in {lesson.repo} (file {lesson.file}). It failed: {lesson.error}"


def build_items(test: dict[str, list[Lesson]], pool: Sequence[Lesson], seed: int = 0) -> list[Item]:
    """A pick and a silence item per test lesson. Distractors: the repo's other lessons, then
    `pool` lessons of other repos; none shares the lesson's (error class, fix tokens) key."""
    rng = random.Random(seed)
    items = []
    for repo, lessons in sorted(test.items()):
        for lesson in lessons:
            others = [o for o in pool if o.repo != repo and key_of(o) != key_of(lesson)]
            shown = _shown(lesson, lessons, others, rng)
            silent = tuple(other for other in shown if other is not lesson)
            situation = situation_of(lesson)
            excused = tuple(o.lesson_id for o in silent if names_fix(lesson.text(), o))
            items.append(Item(f"{lesson.lesson_id}-pick", situation, shown, lesson, excused))
            items.append(Item(f"{lesson.lesson_id}-silence", situation, silent, None))
    return items


def key_of(lesson: Lesson) -> tuple[str, tuple[str, ...]]:
    """What makes two lessons the same failure."""
    return lesson.error_class, lesson.added


def _shown(lesson, lessons, others, rng) -> tuple[Lesson, ...]:
    same_repo = [other for other in lessons if other is not lesson]
    needed = PROMPT_LESSONS - len(same_repo) - 1
    if needed < 0 or len(others) < needed:
        raise ValueError(f"cannot fill {PROMPT_LESSONS} lessons for {lesson.repo}")
    shown = [*same_repo, *rng.sample(others, needed), lesson]
    rng.shuffle(shown)
    return tuple(shown)


_WORD = re.compile(r"[A-Za-z_][\w.\-/]+")


def words(text: str) -> set[str]:
    """Lower-case identifiers, paths and command words."""
    return set(_WORD.findall(text.lower()))


def lexical_scores(item: Item) -> dict[str, float]:
    """Each prompt lesson's inverse-document-frequency overlap with the situation, by lesson id."""
    situation = words(item.situation)
    docs = {
        lesson.lesson_id: words(
            f"{lesson.repo} {lesson.program} {lesson.file} {lesson.failed} {lesson.error_class}"
        )
        for lesson in item.prompt_lessons
    }
    df = Counter(word for doc in docs.values() for word in doc)
    return {
        lesson_id: sum(math.log(len(docs) / df[word]) for word in doc & situation)
        for lesson_id, doc in docs.items()
    }


def lexical_rank(item: Item) -> list[Lesson]:
    """The item's lessons, best first, by `lexical_scores` (ties by lesson id)."""
    scores = lexical_scores(item)
    return sorted(
        item.prompt_lessons, key=lambda lesson: (-scores[lesson.lesson_id], lesson.lesson_id)
    )


def narrowed(item: Item, keep: int, seed: int = 0) -> Item:
    """The ranker's top `keep` lessons in a per-item shuffled order (the ranker's order would give
    the answer away). The applicable lesson stays the answer even if the ranker dropped it."""
    top = lexical_rank(item)[:keep]
    random.Random(f"{seed}:{item.item_id}").shuffle(top)
    shown = {lesson.lesson_id for lesson in top}
    excused = tuple(lesson_id for lesson_id in item.excused if lesson_id in shown)
    return Item(item.item_id, item.situation, tuple(top), item.applies, excused)


def ranker_answer(item: Item) -> str:
    """The ranker alone: its top lesson's note, whatever the situation."""
    return lexical_rank(item)[0].text()


def prompt_row(item: Item) -> dict:
    """The question row `answer_questions.py` reads; the lessons go in as the context file."""
    return {"question_id": item.item_id, "text": ASK.format(situation=item.situation)}


def context_of(item: Item) -> str:
    """The item's system prompt: every lesson in its prompt."""
    return lessons_prompt(list(item.prompt_lessons))


def tokens_of(text: str) -> list[str]:
    """Folded text split on whitespace, edge punctuation stripped."""
    return [stripped for word in fold(text).split() if (stripped := word.strip(_EDGE))]


def contains(haystack: Sequence[str], phrase: Sequence[str]) -> bool:
    """`phrase` occurs as a contiguous run of whole tokens in `haystack`."""
    size = len(phrase)
    return size > 0 and any(
        list(haystack[i : i + size]) == list(phrase) for i in range(len(haystack) - size + 1)
    )


def names_fix(answer: str, lesson: Lesson) -> bool:
    """The answer carries the lesson's fix as whole tokens: every added token, or the command."""
    found = tokens_of(answer)
    every_token = all(contains(found, tokens_of(token)) for token in lesson.added)
    return every_token or contains(found, tokens_of(lesson.fix))


def verdict(item: Item, answer: str) -> dict[str, bool]:
    """Pick, useful note, wrong pick and silence for one answer."""
    wrong = any(
        names_fix(answer, other)
        for other in item.prompt_lessons
        if other is not item.applies and other.lesson_id not in item.excused
    )
    if item.applies is None:
        return {"silent": abstains(answer) and not wrong, "wrong_pick": wrong}
    picked = names_fix(answer, item.applies)
    useful = picked and item.applies.error_class in fold(answer)
    return {"pick": picked and not wrong, "useful": useful and not wrong, "wrong_pick": wrong}


def rates(items: Sequence[Item], answers: dict[str, str]) -> dict[str, float]:
    """Pick, useful and wrong-pick over pick items; silence over silence items."""
    picks = [verdict(i, answers[i.item_id]) for i in items if i.applies is not None]
    quiet = [verdict(i, answers[i.item_id]) for i in items if i.applies is None]
    if not picks or not quiet:
        raise ValueError("a repo needs pick and silence items")
    return {
        "pick": sum(v["pick"] for v in picks) / len(picks),
        "useful": sum(v["useful"] for v in picks) / len(picks),
        "wrong_pick": sum(v["wrong_pick"] for v in picks + quiet) / (len(picks) + len(quiet)),
        "silence": sum(v["silent"] for v in quiet) / len(quiet),
    }


def item_record(item: Item) -> dict:
    """An item as one JSON row: what the answerer reads and what the scorer needs."""
    return {
        **prompt_row(item),
        "context": context_of(item),
        "situation": item.situation,
        "prompt_lessons": [asdict(lesson) for lesson in item.prompt_lessons],
        "applies": asdict(item.applies) if item.applies else None,
        "excused": list(item.excused),
    }


def shows_applicable(record: dict) -> bool:
    """The record's prompt still holds its applicable lesson (a narrowed prompt may drop it)."""
    if record["applies"] is None:
        return False
    return any(
        row["lesson_id"] == record["applies"]["lesson_id"] for row in record["prompt_lessons"]
    )


def item_from(record: dict) -> Item:
    """The Item a record was written from."""

    def lesson(row: dict) -> Lesson:
        return Lesson(**{**row, "added": tuple(row["added"])})

    applies = lesson(record["applies"]) if record["applies"] else None
    shown = tuple(lesson(row) for row in record["prompt_lessons"])
    if applies is not None:
        shown = tuple(applies if other.lesson_id == applies.lesson_id else other for other in shown)
    excused = tuple(record["excused"])
    return Item(record["question_id"], record["situation"], shown, applies, excused)


def own_note_misses(items: Sequence[Item]) -> int:
    """Pick items whose own correct note (the applicable lesson's text) would not score as a pick.
    The scorer is passable only if this is 0."""
    return sum(
        1 for item in items if item.applies and not verdict(item, item.applies.text())["pick"]
    )


def ranker_recall(items: Sequence[Item], depths: Sequence[int] = (1, 3, 5, 10)) -> dict[str, float]:
    """Share of pick items whose applicable lesson the ranker puts in its top k."""
    picks = [item for item in items if item.applies is not None]
    positions = [
        [lesson.lesson_id for lesson in lexical_rank(item)].index(item.applies.lesson_id)
        for item in picks
    ]
    return {
        f"recall_at_{depth}": sum(p < depth for p in positions) / len(picks) for depth in depths
    }


def pick_item_abstention(items: Sequence[Item], answers: dict[str, str]) -> float:
    """Share of pick items the reader answered by saying no lesson applies."""
    picks = [item for item in items if item.applies is not None]
    return sum(abstains(answers[item.item_id]) for item in picks) / len(picks)
