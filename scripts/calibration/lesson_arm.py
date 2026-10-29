"""The lesson arm of the lesson-in-prompt pilot: a lesson text prepended to a task's statement.

A lesson-arm run must never go out without its lesson, so a listed task with a missing or empty
lesson makes loading raise, naming the ids; every record carries the arm and a hash of the exact
lesson text (which words were in the prompt, without storing them). The lessons file is JSON
{instance_id: lesson text} and lives outside the repo next to the run.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path

LESSON_HASH_CHARS = 16  # enough to tell lesson versions apart in a result row
# Same bar as scripts/routeb/sqlglot_leakage.py: shorter lines are syntax glue (`)`, `else:`).
MIN_FIX_LINE_CHARS = 10


class LessonCheck(StrEnum):
    """Whether a lesson carries a line of its own task's gold patch, recorded on every row."""

    CLEAN = "clean"
    CONTAINS_FIX_LINES = "contains fix lines"


class Arm(StrEnum):
    """Which arm a run belongs to; plain is the default, no lesson in the prompt."""

    PLAIN = "plain"
    LESSON = "lesson"
    PERSONAL_LORA = "personal_lora"  # the served sqlglot adapter, no lesson in the prompt
    TEACHER = "teacher"  # Muse Spark or Wonder through egress, earlier tasks only


def load_lessons(path: Path, task_ids: list[str]) -> dict[str, str]:
    """Lesson text per listed task; raises KeyError if a task has no lesson or an empty one."""
    lessons = json.loads(path.read_text())
    missing = [iid for iid in task_ids if not str(lessons.get(iid, "")).strip()]
    if missing:
        raise KeyError(f"{len(missing)} tasks have no lesson in {path}: {missing}")
    return {iid: lessons[iid].strip() for iid in task_ids}


def _flat(text: str) -> str:
    return " ".join(text.split())


def fix_lines(patch: str) -> set[str]:
    """Added and removed lines of the gold patch, whitespace-collapsed, long enough to be code."""
    changed = (
        _flat(line[1:])
        for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    return {
        line for line in changed if len(line) >= MIN_FIX_LINE_CHARS and re.search(r"\w{3}", line)
    }


def check_lesson(lesson: str, patch: str) -> LessonCheck:
    """CONTAINS_FIX_LINES when any gold-patch line appears in the lesson text."""
    flat = _flat(lesson)
    leaked = any(line in flat for line in fix_lines(patch))
    return LessonCheck.CONTAINS_FIX_LINES if leaked else LessonCheck.CLEAN


def check_lessons(lessons: dict[str, str], rows: dict[str, dict]) -> dict[str, LessonCheck]:
    """Check every lesson against its task's gold patch; a row without a patch raises KeyError."""
    missing = sorted(iid for iid in lessons if "patch" not in rows[iid])
    if missing:
        raise KeyError(
            f"{len(missing)} lesson tasks have no gold patch to check against: {missing}"
        )
    return {iid: check_lesson(text, rows[iid]["patch"]) for iid, text in lessons.items()}


def lesson_hash(text: str) -> str:
    """Short sha256 of the lesson text, recorded instead of the text itself."""
    return hashlib.sha256(text.encode()).hexdigest()[:LESSON_HASH_CHARS]


def statement_with_lesson(row: dict, lesson: str) -> dict:
    """A copy of the task row whose problem statement starts with the lesson."""
    return row | {"problem_statement": f"{lesson}\n\n{row['problem_statement']}"}
