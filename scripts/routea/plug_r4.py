"""Plug round 4's single changes, pure: rewritten-lesson queries, near-miss rows from round 3's
validation mistakes, one repository's nightly rows, and the shared operating-point readout.

Every change is read the same way: its threshold is the lowest grid point with wrong pick at most
0.05 and silence at least 0.80 on the same items, so coverage is compared at the same safety.
A shortlisted lesson without a rewrite raises rather than falling back to its template text.
"""

import random
from collections.abc import Sequence
from dataclasses import replace

from plug_judge import JUDGE_SYSTEM, NO, YES, chat, choose, outcome_rates, shortlist
from plug_judge_cli import GRID
from plug_r3 import fit_lowest
from plug_situation import Item

SHORTLIST = 10
NEAR_MISS_P = 0.5  # a wrong lesson the round-3 judge gave at least this P(yes) is a near-miss


class MissingRewriteError(KeyError):
    """A shortlisted lesson has no accepted rewrite."""


def judge_text(situation: str, lesson_text: str) -> str:
    """The judge's question with any lesson wording (round 3's `pair_prompt` layout)."""
    return f"Situation:\n{situation}\n\nLesson:\n{lesson_text}\n\nDoes this lesson apply?"


def rewrite_queries(items: Sequence[Item], rewrites: dict[str, str]) -> list[dict]:
    """Judge queries with every shortlisted lesson's rewrite in place of its template text."""
    found = []
    for item in items:
        for lesson in shortlist(item, SHORTLIST):
            if lesson.lesson_id not in rewrites:
                raise MissingRewriteError(f"no rewrite for shortlisted lesson {lesson.lesson_id}")
            text = judge_text(item.situation, rewrites[lesson.lesson_id])
            found.append(
                {
                    "question_id": f"{item.item_id}::{lesson.lesson_id}",
                    "context": JUDGE_SYSTEM,
                    "text": text,
                }
            )
    return found


def near_miss_rows(items: Sequence[Item], scores: dict[str, float], threshold: float) -> list[dict]:
    """Round-3 validation mistakes as rows: wrong lessons it scored at NEAR_MISS_P or more ("no")
    and applicable lessons it scored under its threshold ("yes")."""
    rows = []
    for item in items:
        for lesson in shortlist(item, SHORTLIST):
            p_yes = scores[f"{item.item_id}::{lesson.lesson_id}"]
            right = item.applies is not None and lesson.lesson_id == item.applies.lesson_id
            excused = lesson.lesson_id in item.excused
            if (right and p_yes < threshold) or (
                not right and not excused and p_yes >= NEAR_MISS_P
            ):
                rows.append(
                    chat(
                        JUDGE_SYSTEM,
                        judge_text(item.situation, lesson.text()),
                        YES if right else NO,
                    )
                )
    return rows


def nightly_rows(
    picks: Sequence[Item], invented: dict[str, list[str]], extra: Sequence[dict], seed: int = 0
) -> list[dict]:
    """One repository's night: each invented situation with its own lesson (yes) and one other
    shortlisted lesson (no), plus `extra` rows (near-misses, habit replay), shuffled."""
    rng = random.Random(seed)
    rows = list(extra)
    for item in picks:
        for situation in invented.get(item.applies.lesson_id, []):
            moved = replace(item, situation=situation)
            others = [
                lesson
                for lesson in shortlist(moved, SHORTLIST)
                if lesson.lesson_id != item.applies.lesson_id
                and lesson.lesson_id not in item.excused
            ]
            rows.append(chat(JUDGE_SYSTEM, judge_text(situation, item.applies.text()), YES))
            if others:
                rows.append(
                    chat(JUDGE_SYSTEM, judge_text(situation, rng.choice(others).text()), NO)
                )
    rng.shuffle(rows)
    return rows


def operating_point(items: Sequence[Item], scores: dict[str, float]) -> dict:
    """The lowest safe grid threshold on these items and the rates there (None if none is)."""
    threshold = fit_lowest(items, lambda cut: choose(items, scores, SHORTLIST, cut), GRID)
    if threshold is None:
        return {"threshold": None, "status": "no safe point"}
    rates = outcome_rates(items, choose(items, scores, SHORTLIST, threshold))
    return {"threshold": threshold, **{key: round(value, 4) for key, value in rates.items()}}
