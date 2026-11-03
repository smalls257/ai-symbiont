"""Nightly rows from lessons a PR review or CI failure taught: "this lesson was needed here".

A reviewer-requested change that a later commit made, or a CI failure that was fixed, is a
human-confirmed mistake. A lesson without a PR link yields no row; the answer is the stored
lesson. Nothing marks these rows trained, and the staleness digest covers mined lessons only.
"""

from collections.abc import Sequence

from symbiont.miner.lesson_context import AuthoredLesson
from symbiont.routeb.lesson_rows import NEXT, TrainingRow, agent_system, chat_row

KIND = "review-needed"
MAX_FILES = 3


def review_rows(repo: str, written: Sequence[AuthoredLesson]) -> list[TrainingRow]:
    """One row per file (up to MAX_FILES) of every lesson that came from a pull request."""
    return [row for lesson in written if lesson.source_url for row in _rows_of(repo, lesson)]


def _rows_of(repo: str, lesson: AuthoredLesson) -> list[TrainingRow]:
    """The situations in which this lesson was needed, each answered by the lesson."""
    answer = _answer(lesson)
    return [
        TrainingRow(lesson.ident, KIND, chat_row(agent_system(repo), situation, answer))
        for situation in _situations(repo, lesson)
    ]


def _situations(repo: str, lesson: AuthoredLesson) -> list[str]:
    """Where the agent is about to act: each file, else the areas, else the repository."""
    if lesson.files:
        return [
            f"Task in {repo}: you are about to edit `{path}`. {NEXT}"
            for path in lesson.files[:MAX_FILES]
        ]
    if lesson.applies.areas:
        area = lesson.applies.areas[0]
        return [f"Task in {repo}: you are about to change code under `{area}`. {NEXT}"]
    return [f"Task in {repo}: you are about to start a change. {NEXT}"]


def _answer(lesson: AuthoredLesson) -> str:
    """The lesson with its provenance label, as the teammate would say it."""
    label = f" ({lesson.source_label})" if lesson.source_label else ""
    return f"Before that, remember{label}: {lesson.text}"
