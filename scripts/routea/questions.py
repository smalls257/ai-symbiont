"""Training examples and held-out reworded questions for the lesson-capacity probe.

Every held-out question is worded with a template that never appears in training and names the
attempt differently (the full command, or program plus file), so recall measures the lesson, not
the prompt. Pure: lessons in, examples out.
"""

from dataclasses import dataclass
from enum import StrEnum

from lessons import Lesson

SYSTEM = "You are a memory model. Answer in one line of plain prose, naming exact commands."


class Asks(StrEnum):
    """Which key details a held-out question asks for; the scorer checks exactly these."""

    FIX = "fix"  # the fix's added tokens
    ERROR = "error"  # the error class
    NOTE = "note"  # both: the one-line warning the memory model exists to write


@dataclass(frozen=True)
class Question:
    """One held-out question about one lesson."""

    question_id: str
    lesson_id: str
    asks: Asks
    text: str


def _training_pairs(lesson: Lesson) -> list[tuple[str, str]]:
    repo, failed, where = lesson.repo, lesson.failed, f"{lesson.program} on {lesson.file}"
    fix_line = f"Run `{lesson.fix}` instead."
    error_line = f"It failed with {lesson.error}."
    return [
        (f"What do you remember about running {where} in {repo}?", lesson.text()),
        (
            f"In {repo}, `{failed}` failed with {lesson.error_class}. What should I run instead?",
            fix_line,
        ),
        (f"What should I run in {repo} instead of `{failed}`?", fix_line),
        (f"What went wrong when I ran `{failed}` in {repo}?", error_line),
        (f"What error did {where} raise in {repo}?", error_line),
        (
            f"I am working in {repo} and about to run `{failed}`. Write a one-line note.",
            lesson.text(),
        ),
    ]


def training_messages(lesson: Lesson) -> list[dict[str, list[dict[str, str]]]]:
    """Self-study Q&A plus situation-to-corrected-action, as mlx-lm chat rows."""
    return [_chat(question, answer) for question, answer in _training_pairs(lesson)]


def _chat(question: str, answer: str) -> dict[str, list[dict[str, str]]]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


def held_out_questions(lesson: Lesson) -> list[Question]:
    """Five reworded questions per lesson; none of these templates is used in training."""
    repo, failed, where = lesson.repo, lesson.failed, f"{lesson.program} against {lesson.file}"
    worded = [
        (Asks.FIX, f"Last time in the {repo} repository, `{failed}` blew up. What command worked?"),
        (Asks.FIX, f"{repo}: which command should replace `{failed}`?"),
        (Asks.ERROR, f"Which exception did `{failed}` hit in {repo}?"),
        (Asks.NOTE, f"Before I run {where} in {repo}, is there anything I should know?"),
        (Asks.NOTE, f"Heads-up needed? I'm about to execute `{failed}` inside {repo}."),
    ]
    return [
        Question(f"{lesson.lesson_id}-{index}", lesson.lesson_id, asks, text)
        for index, (asks, text) in enumerate(worded)
    ]


def lessons_prompt(lessons: list[Lesson]) -> str:
    """The ceiling arm's context: every lesson of the set, one per line."""
    lines = "\n".join(f"- {lesson.text()}" for lesson in lessons)
    return f"{SYSTEM}\nWhat you remember:\n{lines}"
