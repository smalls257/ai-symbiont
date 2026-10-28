"""The lesson arm of the lesson-in-prompt pilot: a lesson text prepended to a task's statement.

Violation prevented: **Silent Fallback**. A pilot that compares a plain arm with a lesson arm is
worthless if a lesson-arm run quietly goes out without its lesson (a typo in an id, an empty
entry). So every listed task must have a non-empty lesson or loading raises, naming the ids; and
every record carries the arm label and a hash of the exact lesson text it saw (**Forensic
Coding**: the result row says which words were in the prompt, without storing the words).

The lessons file is JSON: {instance_id: lesson text}. It lives outside the repo next to the run.
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
