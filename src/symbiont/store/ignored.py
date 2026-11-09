"""Patterns the developer set aside, kept beside the lessons.

A dashboard row can hold several signatures (a reviewer's merge), so ignoring a row stores them
all under one label and one `row_id`, and restoring any of them brings the whole row back.

An ignored pattern is hidden on read (`Store.lessons`) and counted as IGNORED on every mining,
but mining still saves its lessons, so restoring needs no re-mine, also after a re-mine.
"""

import json
import sqlite3
from collections.abc import Sequence

from symbiont.miner.painpoint import Signal, Signature

SCHEMA = """
CREATE TABLE IF NOT EXISTS ignored (
    project TEXT NOT NULL, signal TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL,
    row_id TEXT NOT NULL,
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

    def add(self, project: str, signatures: Sequence[Signature], label: str) -> None:
        """Set one row's patterns aside; `label` is its title now, so the list reads as prose."""
        row_id = f"{signatures[0].signal.value}:{key_json(signatures[0])}"
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO ignored VALUES (?, ?, ?, ?, ?)",
                [(project, sig.signal.value, key_json(sig), label, row_id) for sig in signatures],
            )

    def remove(self, project: str, signature: Signature) -> bool:
        """Bring back the whole row that holds `signature`; False when it was not ignored."""
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM ignored WHERE project=? AND row_id=(SELECT row_id FROM ignored "
                "WHERE project=? AND signal=? AND key=?)",
                (project, project, signature.signal.value, key_json(signature)),
            )
        return cursor.rowcount > 0

    def signatures(self, project: str) -> frozenset[Signature]:
        """Every ignored signature of `project`."""
        return frozenset(sig for sigs, _ in self.listed(project) for sig in sigs)

    def listed(self, project: str) -> list[tuple[tuple[Signature, ...], str]]:
        """(signatures, label) of every ignored row of `project`, oldest first."""
        rows = self._db.execute(
            "SELECT row_id, signal, key, label FROM ignored WHERE project=? ORDER BY rowid",
            (project,),
        )
        rowed: dict[str, tuple[list[Signature], str]] = {}
        for row_id, signal, key, label in rows:
            rowed.setdefault(row_id, ([], label))[0].append(
                Signature(Signal(signal), tuple(json.loads(key)))
            )
        return [(tuple(sigs), label) for sigs, label in rowed.values()]
