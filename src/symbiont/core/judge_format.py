"""The exact text the round-4 judge was trained and scored on, built from a product lesson.

The judge adapters learned one layout (plug/round3 `plug_judge.pair_prompt`, `plug_situation.
situation_of`, `lessons.Lesson.text`); any other wording moves its P(yes) off the frozen
thresholds. tests/core/test_judge_format.py pins the bytes against that builder's output.
"""

import re
from dataclasses import dataclass

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal

JUDGE_SYSTEM = (
    "You decide whether one stored lesson applies to what a coding agent is doing now. "
    "Answer yes or no."
)
_RAN_COMMAND = re.compile(r"ran `([^`]+)`")


@dataclass(frozen=True)
class JudgeableLesson:
    """The four fields of a research lesson that its text is made of."""

    repo: str
    failed: str
    error: str
    fix: str


def judge_situation(command: str, repo: str, file: str, error: str) -> str:
    """What the agent is doing now: the failed command, its repository, file and error line."""
    return f"Ran `{command}` in {repo} (file {file}). It failed: {error}"


def judge_lesson_text(lesson: JudgeableLesson) -> str:
    """One lesson as the judge read it in training."""
    return (
        f"In {lesson.repo}, `{lesson.failed}` failed with {lesson.error}; "
        f"run `{lesson.fix}` instead."
    )


def judge_input(situation: str, lesson: JudgeableLesson) -> str:
    """The judge's user message for one situation and one lesson."""
    text = judge_lesson_text(lesson)
    return f"Situation:\n{situation}\n\nLesson:\n{text}\n\nDoes this lesson apply?"


def judgeable(lesson: Lesson, project: str) -> JudgeableLesson | None:
    """The lesson in research fields, or None if the judge never saw its shape (no fix command)."""
    if lesson.pain_point.signature.signal is not Signal.FAILED_COMMAND:
        return None
    lines = lesson.quote.splitlines()
    fix = next(
        (found.group(1) for step in lesson.resolution if (found := _RAN_COMMAND.search(step))), None
    )
    if len(lines) < 2 or not lines[0].startswith("$ ") or fix is None:
        return None
    return JudgeableLesson(project.replace("__", "/", 1), lines[0][2:], lines[-1], fix)


def fix_commands(lesson: Lesson) -> tuple[str, ...]:
    """Every command the lesson's resolution ran (twins pool several), in order."""
    found = (_RAN_COMMAND.search(step) for step in lesson.resolution)
    return tuple(match.group(1) for match in found if match)
