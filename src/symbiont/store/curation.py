"""Lessons written in plain words, verdicts on mined pain points, and decided correction ids.

The session's model (or the developer) writes these through the service; they live beside the
mined lessons in the same database and carry no record text beyond what the writer chose.
"""

import json
import sqlite3

from symbiont.miner.lesson_context import AuthoredLesson, LessonKind, Review, Severity, Verdict
from symbiont.store.contexts import applies_from, applies_json


class Curation:
    """Reads and writes the authored, reviews and decided tables of a store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def add_authored(self, project: str, lesson: AuthoredLesson) -> None:
        """Store a written lesson; the same id replaces its earlier version."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO authored VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson.ident,
                    project,
                    lesson.text,
                    lesson.kind,
                    json.dumps(list(lesson.files)),
                    lesson.source_label,
                    lesson.severity,
                    applies_json(lesson.applies),
                ),
            )

    def authored(self, project: str) -> list[AuthoredLesson]:
        """The project's written lessons, oldest first."""
        rows = self._db.execute(
            "SELECT id, text, kind, files, source_label, severity, applies FROM authored "
            "WHERE project=? ORDER BY rowid",
            (project,),
        )
        return [
            AuthoredLesson(
                row[0],
                row[1],
                LessonKind(row[2]),
                tuple(json.loads(row[3])),
                row[4],
                Severity(row[5]),
                applies_from(row[6]),
            )
            for row in rows
        ]

    def find_authored(self, wanted: str) -> tuple[str, AuthoredLesson] | None:
        """(project, lesson) for the written lesson with id `wanted`, or None."""
        for project in self._db.execute("SELECT DISTINCT project FROM authored").fetchall():
            for item in self.authored(project[0]):
                if item.ident == wanted:
                    return project[0], item
        return None

    def forget_authored(self, project: str, ident: str) -> bool:
        """Delete a written lesson and the words and answers kept for it; False if none matched."""
        with self._db:
            gone = self._db.execute(
                "DELETE FROM authored WHERE project=? AND id=?", (project, ident)
            ).rowcount
            self._db.execute(
                "DELETE FROM contexts WHERE project=? AND lesson_id=?", (project, ident)
            )
            self._db.execute(
                "DELETE FROM review_overrides WHERE project=? AND lesson_id=?", (project, ident)
            )
        return gone > 0

    def save_review(self, project: str, lesson_id: str, review: Review) -> None:
        """Store the verdict for a mined lesson."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    lesson_id,
                    project,
                    review.verdict,
                    review.rule,
                    review.title,
                    review.merge_with,
                    applies_json(review.applies),
                ),
            )

    def reviews(self, project: str) -> dict[str, Review]:
        """The project's verdicts by lesson id."""
        rows = self._db.execute(
            "SELECT lesson_id, verdict, rule, title, merge_with, applies "
            "FROM reviews WHERE project=?",
            (project,),
        )
        return {
            row[0]: Review(Verdict(row[1]), row[2], row[3], row[4], applies_from(row[5]))
            for row in rows
        }

    def decide(self, project: str, candidate_ids: list[str]) -> None:
        """Remember which correction candidates were judged, so they are not offered again."""
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO decided VALUES (?, ?)",
                [(project, ident) for ident in candidate_ids],
            )

    def decided(self, project: str) -> frozenset[str]:
        """The candidate ids already judged."""
        rows = self._db.execute("SELECT candidate_id FROM decided WHERE project=?", (project,))
        return frozenset(row[0] for row in rows)
