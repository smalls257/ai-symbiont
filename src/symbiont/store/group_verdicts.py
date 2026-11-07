"""The one-sentence verdicts the session's model wrote for failure groups, kept across re-mines.

Developer-owned like summaries: NOT in `REPLACED_TABLES`, because a re-mine that emptied them
would make the model redo, and the developer pay for, every sentence. A group's key is its
stable fingerprint, so a sentence finds its group again after a re-mine.
"""

import sqlite3
from collections.abc import Mapping
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS group_verdicts (
    project TEXT NOT NULL, key TEXT NOT NULL, sentence TEXT NOT NULL, written_on TEXT NOT NULL,
    PRIMARY KEY (project, key)
);
"""


class GroupVerdicts:
    """Reads and writes the group_verdicts table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(self, project: str, sentences: Mapping[str, str], day: date) -> None:
        """Keep the sentences; one written again for the same group replaces the earlier."""
        rows = [(project, key, text, day.isoformat()) for key, text in sentences.items()]
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO group_verdicts VALUES (?,?,?,?)", rows)

    def sentences(self, project: str) -> dict[str, str]:
        """The sentence of every group of `project` that has one, by group key."""
        rows = self._db.execute(
            "SELECT key, sentence FROM group_verdicts WHERE project=?", (project,)
        )
        return dict(rows)
