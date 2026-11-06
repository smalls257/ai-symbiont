"""Patterns the developer set aside: one row per signature, kept beside the lessons.

An ignored pattern is hidden by every read of the lessons (`Store.lessons`) and held back as
IGNORED on every later mining, and it stays listed here with its title so it can be restored.
The row survives a re-mining because a signature is stable; nothing is deleted from the lessons.
"""

import json
import sqlite3

from symbiont.miner.painpoint import Signal, Signature

SCHEMA = """
CREATE TABLE IF NOT EXISTS ignored (
    project TEXT NOT NULL, signal TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL,
    PRIMARY KEY (project, signal, key)
);
"""


def key_json(signature: Signature) -> str:
    """The signature's key as stored: a JSON list."""
    return json.dumps(list(signature.key))


class IgnoredPatterns:
    """Reads and writes the ignored table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def add(self, project: str, signature: Signature, label: str) -> None:
        """Set the pattern aside; `label` is its title now, so the Ignored list reads as prose."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO ignored VALUES (?, ?, ?, ?)",
                (project, signature.signal.value, key_json(signature), label),
            )

    def remove(self, project: str, signature: Signature) -> bool:
        """Bring the pattern back; False when it was not ignored."""
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM ignored WHERE project=? AND signal=? AND key=?",
                (project, signature.signal.value, key_json(signature)),
            )
        return cursor.rowcount > 0

    def signatures(self, project: str) -> frozenset[Signature]:
        """Every ignored signature of `project`."""
        return frozenset(signature for signature, _ in self.listed(project))

    def listed(self, project: str) -> list[tuple[Signature, str]]:
        """(signature, label) of every ignored pattern of `project`, oldest first."""
        rows = self._db.execute(
            "SELECT signal, key, label FROM ignored WHERE project=? ORDER BY rowid", (project,)
        )
        return [
            (Signature(Signal(signal), tuple(json.loads(key))), label)
            for signal, key, label in rows
        ]
