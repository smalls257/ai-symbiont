"""Route B rows for a cross-repo "habits" adapter, split so whole repositories are held out.

Self-study Q&A and situation-to-corrected-action pairs per lesson, as mlx-lm chat rows. Scoring
on repositories the adapter trained on would reward memorized repos, so whole repositories are
held out, and held-out questions use wordings training never sees. Token length is checked by
`check_tokens.py`. Pure: lessons in, rows out.
"""

import hashlib
from collections.abc import Iterable
from enum import StrEnum

from lessons import IssueKind, Lesson

SYSTEM = (
    "You are a coding assistant. You keep habits learned from code review and answer in plain "
    "prose."
)
HELD_OUT_SHARE = 0.20  # at least this share of lessons, in whole repositories, never trains
VALID_SHARE = 0.05  # at least this share, in whole repositories, measures validation loss

SITUATION = {
    IssueKind.TESTS_MISSING: "the change is ready and I have not touched the tests",
    IssueKind.ERROR_HANDLING: "the new code calls things that can fail",
    IssueKind.WRONG_MODULE: "I am adding a new helper function for it",
    IssueKind.API_MISUSE: "the new code calls a library function I have not used here before",
    IssueKind.NAMING_CONVENTION: "I am adding new functions and variables",
}
# The same situations in other words, for held-out questions only.
HELD_OUT_SITUATION = {
    IssueKind.TESTS_MISSING: "the implementation is done but the test suite is unchanged",
    IssueKind.ERROR_HANDLING: "the new code makes network and file calls",
    IssueKind.WRONG_MODULE: "I want to drop a new utility function into this file",
    IssueKind.API_MISUSE: "I am calling a third-party library method for the first time",
    IssueKind.NAMING_CONVENTION: "I introduced several new identifiers",
}
HABIT = {
    IssueKind.TESTS_MISSING: "a change that came without tests",
    IssueKind.ERROR_HANDLING: "error handling",
    IssueKind.WRONG_MODULE: "code placed in the wrong module",
    IssueKind.API_MISUSE: "an API used the wrong way",
    IssueKind.NAMING_CONVENTION: "names that break the project's conventions",
}


class Split(StrEnum):
    """Which part of the data a repository's lessons go to."""

    TRAIN = "train"
    VALID = "valid"
    HELD_OUT = "held_out"


def assign_splits(lessons_per_repo: dict[str, int]) -> dict[str, Split]:
    """Whole repositories to splits: in stable hash order, held out first, then valid, then train.

    A fixed hash bucket per repository would hold out almost nothing when there are few
    repositories, so repositories are taken in hash order until each share of lessons is met.
    """
    total = sum(lessons_per_repo.values())
    order = sorted(lessons_per_repo, key=lambda repo: hashlib.sha256(repo.encode()).hexdigest())
    splits: dict[str, Split] = {}
    held, valid = 0, 0
    for repo in order:
        if held < HELD_OUT_SHARE * total:
            splits[repo], held = Split.HELD_OUT, held + lessons_per_repo[repo]
        elif valid < VALID_SHARE * total:
            splits[repo], valid = Split.VALID, valid + lessons_per_repo[repo]
        else:
            splits[repo] = Split.TRAIN
    return splits


def training_pairs(lesson: Lesson) -> list[tuple[str, str]]:
    """Self-study Q&A and situation-to-corrected-action pairs for one lesson."""
    where, kind = lesson.where(), lesson.kind
    return [
        (
            f"What happened when an agent changed {where} in a Python project, and how was "
            "it resolved?",
            f"{lesson.what_happened()} {lesson.how_resolved()}",
        ),
        (
            f"I am changing {where} in a Python project and {SITUATION[kind]}. "
            "What should I check before I finish?",
            lesson.check(),
        ),
        (f"What habit did code review teach about {HABIT[kind]}?", lesson.check()),
        (f"Recall the review lesson about {where}.", lesson.text()),
    ]


def held_out_questions(lesson: Lesson) -> list[dict[str, str]]:
    """Reworded questions for a held-out lesson; neither wording nor situation is trained on."""
    where, situation = lesson.where(), HELD_OUT_SITUATION[lesson.kind]
    asked = [
        f"Working on {where} in a Python codebase: {situation}. Anything to verify before I push?",
        f"Quick plan check for {where}: {situation}. What would a careful reviewer ask me to do?",
    ]
    return [
        {
            "question_id": f"{lesson.lesson_id}-{number}",
            "lesson_id": lesson.lesson_id,
            "kind": lesson.kind.value,
            "text": text,
        }
        for number, text in enumerate(asked)
    ]


def chat_row(question: str, answer: str) -> dict[str, list[dict[str, str]]]:
    """One mlx-lm chat row: system, user, assistant."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


def rows_for(lessons: Iterable[Lesson]) -> list[dict[str, list[dict[str, str]]]]:
    """Chat rows for lessons, each question-and-answer pair once."""
    seen: set[tuple[str, str]] = set()
    rows = []
    for lesson in lessons:
        for pair in training_pairs(lesson):
            if pair in seen:
                continue
            seen.add(pair)
            rows.append(chat_row(*pair))
    return rows
