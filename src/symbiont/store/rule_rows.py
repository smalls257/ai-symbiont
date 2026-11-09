"""Rule candidates kept per project, in the transaction of the lessons they were mined with.

Rows hold scrubbed one-line text (at most 240 characters) and its distinctive terms, never a
whole turn. Grouping is not stored: it is recomputed from the rows, so the grouping rules can
change without a re-mine.
"""

import json
import sqlite3
from collections.abc import Sequence

from symbiont.miner.rule_candidates import RuleCandidate

TABLES = ("rule_candidates",)
SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_candidates (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    text TEXT NOT NULL, terms TEXT NOT NULL, source TEXT NOT NULL
);
"""


def insert_rule_candidates(
    db: sqlite3.Connection, project: str, candidates: Sequence[RuleCandidate]
) -> None:
    """Add one mining's candidates; the caller deleted the old ones in its transaction."""
    db.executemany(
        "INSERT INTO rule_candidates VALUES (?, ?, ?, ?, ?, ?)",
        [
            (project, c.session_id, c.step, c.text, json.dumps(sorted(c.terms)), c.source)
            for c in candidates
        ],
    )


def read_rule_candidates(db: sqlite3.Connection, project: str) -> list[RuleCandidate]:
    """The candidates of the last mining, in the order they were mined."""
    rows = db.execute(
        "SELECT session_id, step, text, terms, source FROM rule_candidates "
        "WHERE project=? ORDER BY rowid",
        (project,),
    ).fetchall()
    return [
        RuleCandidate(sid, int(step), text, frozenset(json.loads(terms)), source)
        for sid, step, text, terms, source in rows
    ]
