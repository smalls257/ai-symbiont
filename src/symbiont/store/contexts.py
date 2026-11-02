"""The developer's own words about a lesson, kept in the store beside the lessons.

They are the developer's text, not record text, so they live in their own table and survive a
re-mining: a lesson id (session, step, signal) is stable.
"""

import sqlite3

from symbiont.miner.lesson_context import LessonContext, Priority


class LessonContexts:
    """Reads and writes the contexts table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(self, lesson_id: str, project: str, context: LessonContext) -> None:
        """Replace the words for a lesson."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO contexts VALUES (?, ?, ?, ?, ?)",
                (lesson_id, project, context.text, int(context.intentional), context.priority),
            )

    def get(self, lesson_id: str) -> LessonContext | None:
        """The words for a lesson, or None when the developer added none."""
        row = self._db.execute(
            "SELECT text, intentional, priority FROM contexts WHERE lesson_id=?", (lesson_id,)
        ).fetchone()
        return None if row is None else _context(row)

    def all(self, project: str) -> dict[str, LessonContext]:
        """Every lesson's words in `project`, by lesson id."""
        rows = self._db.execute(
            "SELECT lesson_id, text, intentional, priority FROM contexts WHERE project=?",
            (project,),
        )
        return {row[0]: _context(row[1:]) for row in rows}


def _context(row: tuple[str, int, str]) -> LessonContext:
    """A LessonContext from a stored row."""
    return LessonContext(row[0], bool(row[1]), Priority(row[2]))
