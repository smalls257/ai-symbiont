"""The developer's own words about a lesson, kept in the store beside the lessons.

They are the developer's text, not record text, so they live in their own table and survive a
re-mining: a lesson id (session, step, signal) is stable.
"""

import json
import sqlite3

from symbiont.miner.lesson_context import (
    AppliesTo,
    LessonContext,
    Priority,
    ReviewOverride,
)


class LessonContexts:
    """Reads and writes the contexts table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(self, lesson_id: str, project: str, context: LessonContext) -> None:
        """Replace the words for a lesson."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO contexts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lesson_id,
                    project,
                    context.text,
                    int(context.intentional),
                    context.priority,
                    applies_json(context.applies),
                ),
            )

    def save_override(self, lesson_id: str, project: str, choice: ReviewOverride) -> None:
        """Remember the developer's answer to a reviewer verdict on this lesson."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO review_overrides VALUES (?, ?, ?)",
                (lesson_id, project, choice.value),
            )

    def overrides(self, project: str) -> dict[str, ReviewOverride]:
        """Lesson id -> the developer's answer, for every answered lesson in `project`."""
        rows = self._db.execute(
            "SELECT lesson_id, choice FROM review_overrides WHERE project=?", (project,)
        )
        return {row[0]: ReviewOverride(row[1]) for row in rows}

    def get(self, lesson_id: str) -> LessonContext | None:
        """The words for a lesson, or None when the developer added none."""
        row = self._db.execute(
            "SELECT text, intentional, priority, applies FROM contexts WHERE lesson_id=?",
            (lesson_id,),
        ).fetchone()
        return None if row is None else _context(row)

    def all(self, project: str) -> dict[str, LessonContext]:
        """Every lesson's words in `project`, by lesson id."""
        rows = self._db.execute(
            "SELECT lesson_id, text, intentional, priority, applies FROM contexts WHERE project=?",
            (project,),
        )
        return {row[0]: _context(row[1:]) for row in rows}


def _context(row: tuple[str, int, str, str]) -> LessonContext:
    """A LessonContext from a stored row."""
    return LessonContext(row[0], bool(row[1]), Priority(row[2]), applies_from(row[3]))


def applies_json(applies: AppliesTo) -> str:
    """The tags as stored."""
    return json.dumps({"terms": list(applies.terms), "areas": list(applies.areas)})


def applies_from(stored: str) -> AppliesTo:
    """The tags from their stored JSON."""
    saved = json.loads(stored)
    return AppliesTo(tuple(saved["terms"]), tuple(saved["areas"]))
