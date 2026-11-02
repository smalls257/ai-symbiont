"""Questions that cross projects: which projects have lessons, and who owns a lesson id."""

import sqlite3

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signature
from symbiont.miner.trained import lesson_id
from symbiont.store.lesson_rows import lesson_from_json


class LessonCatalog:
    """Reads the lessons table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def projects(self) -> list[str]:
        """Every project that has at least one stored lesson, sorted."""
        rows = self._db.execute("SELECT DISTINCT project FROM lessons ORDER BY project")
        return [row[0] for row in rows]

    def forget(self, project: str, trouble: Signature) -> int:
        """Delete the lessons of `project` about this kind of trouble; returns how many.

        Re-mining would bring them back, so the caller also mutes the trouble (`store.repos`).
        """
        rows = self._db.execute("SELECT rowid, body FROM lessons WHERE project=?", (project,))
        doomed = [
            row for row, body in rows if lesson_from_json(body).pain_point.signature == trouble
        ]
        with self._db:
            self._db.executemany("DELETE FROM lessons WHERE rowid=?", [(row,) for row in doomed])
        return len(doomed)

    def find(self, wanted: str) -> tuple[str, Lesson] | None:
        """(project, lesson) for the lesson id `wanted`, or None when no stored lesson has it."""
        for project, body in self._db.execute("SELECT project, body FROM lessons"):
            lesson = lesson_from_json(body)
            if lesson_id(lesson) == wanted:
                return project, lesson
        return None
