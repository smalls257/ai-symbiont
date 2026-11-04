"""The exact text the round-4 judge was trained and scored on, built from a product lesson.

The judge adapters learned one layout (plug/round3 `plug_judge.pair_prompt`, `plug_situation.
situation_of`, `lessons.Lesson.text`); any other wording moves its P(yes) off the frozen
thresholds. tests/core/test_judge_format.py pins the bytes against that builder's output.
"""

import re
from dataclasses import dataclass

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal
from symbiont.records.schema import Record

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


def failure_situation(record: Record, project: str) -> str | None:
    """The judge's situation for a command that just failed, or None when it has no text to judge.

    Built as the lessons were: the command, the repository, the file the step touched and the last
    line of the output, which is where the error is.
    """
    lines = record.raw.strip().splitlines()
    if not record.command or not lines:
        return None
    file = record.files[0] if record.files else "n/a"
    return judge_situation(record.command, project.replace("__", "/", 1), file, lines[-1])


def judge_lesson_text(lesson: JudgeableLesson) -> str:
    """One lesson as the judge read it in training."""
    return (
        f"In {lesson.repo}, `{lesson.failed}` failed with {lesson.error}; "
        f"run `{lesson.fix}` instead."
    )


def judge_input_text(situation: str, lesson_text: str) -> str:
    """The judge's user message for a situation and a lesson already written out as text."""
    return f"Situation:\n{situation}\n\nLesson:\n{lesson_text}\n\nDoes this lesson apply?"


def judge_input(situation: str, lesson: JudgeableLesson) -> str:
    """The judge's user message for one situation and one lesson."""
    return judge_input_text(situation, judge_lesson_text(lesson))


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
