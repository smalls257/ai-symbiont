"""Plug round 3: a pairwise judge (situation, one lesson) -> applies?, over the ranker's shortlist.

The judge never writes a lesson: the note is the stored text of the shortlisted lesson it scores
highest, and it stays silent when that score is under a threshold fitted on validation items only.
So it cannot confabulate a lesson. Training pairs come from meta-train lessons, balanced, with the
ranker's high-ranked wrong lessons as hard negatives. Pure: items and scores in, rows and rates out.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from l2l_quick import chat
from lessons import Lesson
from plug_situation import Item, lexical_rank

JUDGE_SYSTEM = (
    "You decide whether one stored lesson applies to what a coding agent is doing now. "
    "Answer yes or no."
)
YES, NO = "yes", "no"


def pair_prompt(situation: str, lesson: Lesson) -> str:
    """The judge's question for one situation and one lesson."""
    return f"Situation:\n{situation}\n\nLesson:\n{lesson.text()}\n\nDoes this lesson apply?"


def shortlist(item: Item, size: int) -> list[Lesson]:
    """The ranker's top `size` lessons for the item."""
    return lexical_rank(item)[:size]


def judge_rows(items: Sequence[Item], size: int, seed: int = 0) -> list[dict]:
    """Balanced training rows: each pick item's own lesson (yes) and as many hard negatives (no):
    shortlisted lessons that do not apply, from pick items and from silence items' near misses."""
    rng = random.Random(seed)
    positives, negatives = [], []
    for item in items:
        excused = set(item.excused)
        for lesson in shortlist(item, size):
            applies = item.applies is not None and lesson.lesson_id == item.applies.lesson_id
            if applies:
                positives.append(chat(JUDGE_SYSTEM, pair_prompt(item.situation, lesson), YES))
            elif lesson.lesson_id not in excused:
                negatives.append(chat(JUDGE_SYSTEM, pair_prompt(item.situation, lesson), NO))
    if len(negatives) < len(positives):
        raise ValueError(
            f"{len(negatives)} hard negatives cannot balance {len(positives)} positives"
        )
    rows = positives + rng.sample(negatives, len(positives))
    rng.shuffle(rows)
    return rows


def judge_mix(
    items: Sequence[Item],
    size: int,
    phrasings: Sequence[Callable[[Lesson], str]],
    source_of: Callable[[Item], Lesson],
    habit_rows: list[dict],
) -> dict:
    """Round 3's training mix: judge rows for every item under its own situation and each extra
    phrasing (balanced over all), plus the habit rows; with the counts the prereg pins."""
    variants = list(items) + [
        replace(item, situation=phrase(source_of(item))) for phrase in phrasings for item in items
    ]
    judged = judge_rows(variants, size)
    rows = judged + list(habit_rows)
    random.Random(0).shuffle(rows)
    yes = sum(1 for row in judged if row["messages"][2]["content"] == YES)
    return {
        "rows": rows,
        "counts": {
            "phrasings": 1 + len(phrasings),
            "positives": yes,
            "negatives": len(judged) - yes,
            "habit_rows": len(habit_rows),
            "total": len(rows),
            "habit_share": round(len(habit_rows) / len(rows), 4),
        },
    }


def judge_queries(items: Sequence[Item], size: int) -> list[dict]:
    """One query row per (item, shortlisted lesson), for the CUDA scorer."""
    return [
        {
            "question_id": f"{item.item_id}::{lesson.lesson_id}",
            "context": JUDGE_SYSTEM,
            "text": pair_prompt(item.situation, lesson),
        }
        for item in items
        for lesson in shortlist(item, size)
    ]


@dataclass(frozen=True)
class Choice:
    """The judge's decision on one item: the chosen lesson id (None = silent) and its score."""

    item_id: str
    lesson_id: str | None
    score: float


def choose(
    items: Sequence[Item], scores: dict[str, float], size: int, threshold: float
) -> list[Choice]:
    """Highest-scoring shortlisted lesson per item, or silence under the threshold."""
    found = []
    for item in items:
        scored = [
            (scores[f"{item.item_id}::{shown.lesson_id}"], shown.lesson_id)
            for shown in shortlist(item, size)
        ]
        best, lesson_id = max(scored)
        found.append(Choice(item.item_id, lesson_id if best >= threshold else None, best))
    return found


def outcome_rates(items: Sequence[Item], choices: Sequence[Choice]) -> dict[str, float]:
    """Pick (right lesson on pick items), silence (on silence items), wrong pick, coverage."""
    by_id = {choice.item_id: choice for choice in choices}
    picks = [i for i in items if i.applies is not None]
    quiet = [i for i in items if i.applies is None]
    right = sum(by_id[i.item_id].lesson_id == i.applies.lesson_id for i in picks)
    answered_pick = sum(by_id[i.item_id].lesson_id is not None for i in picks)
    answered_quiet = sum(by_id[i.item_id].lesson_id is not None for i in quiet)
    answered = answered_pick + answered_quiet
    return {
        "pick": right / len(picks),
        "silence": 1 - answered_quiet / len(quiet),
        "wrong_pick": (answered - right) / len(items),
        "coverage": answered_pick / len(picks),
        "precision": right / answered if answered else 1.0,
    }


def curve(
    items: Sequence[Item], scores: dict[str, float], size: int, thresholds: Sequence[float]
) -> list[dict]:
    """Precision, coverage, pick and silence at each threshold."""
    return [
        {"threshold": t, **outcome_rates(items, choose(items, scores, size, t))} for t in thresholds
    ]


def fit_threshold(
    items: Sequence[Item], scores: dict[str, float], size: int, grid: Sequence[float]
) -> float:
    """The lowest threshold whose silence is at least 0.80 and wrong pick at most 0.05 on these
    (validation) items; raises if none is."""
    for row in curve(items, scores, size, sorted(grid)):
        if row["silence"] >= 0.80 and row["wrong_pick"] <= 0.05:
            return row["threshold"]
    raise ValueError("no threshold reaches silence 0.80 with wrong pick 0.05 on the fitting items")
