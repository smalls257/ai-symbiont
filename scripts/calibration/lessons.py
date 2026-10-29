"""The lesson arm of the lesson-in-prompt pilot: a lesson text prepended to a task's statement.

A lesson-arm run must never go out without its lesson, so a listed task with a missing or empty
lesson makes loading raise, naming the ids; every record carries the arm and a hash of the exact
lesson text (which words were in the prompt, without storing them). The lessons file is JSON
{instance_id: lesson text} and lives outside the repo next to the run.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path

LESSON_HASH_CHARS = 16  # enough to tell lesson versions apart in a result row


class Arm(StrEnum):
    """Which arm a run belongs to; plain is the default, no lesson in the prompt."""

    PLAIN = "plain"
    LESSON = "lesson"
    PERSONAL_LORA = "personal_lora"  # the served sqlglot adapter, no lesson in the prompt


def load_lessons(path: Path, task_ids: list[str]) -> dict[str, str]:
    """Lesson text per listed task; raises KeyError if a task has no lesson or an empty one."""
    lessons = json.loads(path.read_text())
    missing = [iid for iid in task_ids if not str(lessons.get(iid, "")).strip()]
    if missing:
        raise KeyError(f"{len(missing)} tasks have no lesson in {path}: {missing}")
    return {iid: lessons[iid].strip() for iid in task_ids}


def lesson_hash(text: str) -> str:
    """Short sha256 of the lesson text, recorded instead of the text itself."""
    return hashlib.sha256(text.encode()).hexdigest()[:LESSON_HASH_CHARS]


def statement_with_lesson(row: dict, lesson: str) -> dict:
    """A copy of the task row whose problem statement starts with the lesson."""
    return row | {"problem_statement": f"{lesson}\n\n{row['problem_statement']}"}
