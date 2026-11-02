"""Plug round 3's baseline: round 2's V2 reader with a confidence threshold on its own pick.

V2 writes a note; the lesson it names is the applicable one when the round-2 scorer calls it a
pick, else the first other shown lesson whose fix it states, else none (silent). Its confidence is
V2's mean log-probability of that lesson's stored note, as its reply to the same prompt. Under a
threshold it stays silent. Pure: items, answers and confidences in, queries and curves out.
"""

from collections.abc import Sequence

from plug_judge import Choice, outcome_rates
from plug_situation import ASK, Item, context_of, names_fix, verdict


def named_lesson(item: Item, answer: str) -> str | None:
    """The lesson id the answer names, judged as the round-2 scorer does."""
    if item.applies is not None and verdict(item, answer).get("pick"):
        return item.applies.lesson_id
    for lesson in item.prompt_lessons:
        if (
            lesson is not item.applies
            and lesson.lesson_id not in item.excused
            and names_fix(answer, lesson)
        ):
            return lesson.lesson_id
    return None


def note_queries(items: Sequence[Item], answers: dict[str, str]) -> list[dict]:
    """One scoring row per named lesson: V2's prompt, and the stored note as the reply."""
    rows = []
    for item in items:
        lesson_id = named_lesson(item, answers[item.item_id])
        if lesson_id is None:
            continue
        note = next(
            lesson for lesson in item.prompt_lessons if lesson.lesson_id == lesson_id
        ).text()
        rows.append(
            {
                "question_id": item.item_id,
                "context": context_of(item),
                "text": ASK.format(situation=item.situation),
                "reply": note,
            }
        )
    return rows


def thresholded(
    items: Sequence[Item], answers: dict[str, str], confidence: dict[str, float], threshold: float
) -> list[Choice]:
    """V2's named lesson where its confidence reaches the threshold, else silence."""
    choices = []
    for item in items:
        lesson_id = named_lesson(item, answers[item.item_id])
        # A named lesson must have a score: a missing one raises, never reads as silence.
        score = confidence[item.item_id] if lesson_id is not None else float("-inf")
        keep = lesson_id is not None and score >= threshold
        choices.append(Choice(item.item_id, lesson_id if keep else None, score))
    return choices


def seed_curve(
    items: Sequence[Item], seeds: Sequence[tuple[dict, dict]], thresholds: Sequence[float]
) -> list[dict]:
    """Rates at each threshold, averaged over seeds; each seed is (answers, confidences)."""
    rows = []
    for threshold in thresholds:
        per_seed = [outcome_rates(items, thresholded(items, a, c, threshold)) for a, c in seeds]
        mean = {key: sum(r[key] for r in per_seed) / len(per_seed) for key in per_seed[0]}
        rows.append({"threshold": threshold, **mean})
    return rows


def fit_seed_threshold(
    items: Sequence[Item], seeds: Sequence[tuple[dict, dict]], grid: Sequence[float]
) -> float:
    """The lowest threshold whose seed-mean silence is at least 0.80 and wrong pick at most 0.05."""
    for row in seed_curve(items, seeds, sorted(grid)):
        if row["silence"] >= 0.80 and row["wrong_pick"] <= 0.05:
            return row["threshold"]
    raise ValueError("no threshold reaches silence 0.80 with wrong pick 0.05 on the fitting items")
