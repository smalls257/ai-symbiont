"""The developer's review status of each failure group, kept across re-mines.

Triage is developer-owned state like `ignored`, so it is
NOT in `REPLACED_TABLES`: a re-mine rebuilds the groups but never forgets which were Resolved.
`group_key` is the opaque fingerprint of a failure group; this table treats it as text.
"""

import sqlite3
from datetime import date

from symbiont.core.triage import GroupState, ReturnRule, TriageRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS triage (
    project TEXT NOT NULL, group_key TEXT NOT NULL, state TEXT NOT NULL,
    return_rule TEXT, after_sessions INTEGER, changed_on TEXT NOT NULL, taught_on TEXT,
    PRIMARY KEY (project, group_key)
);
"""


class GroupTriage:
    """Reads and writes the triage table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(self, project: str, group_key: str, row: TriageRow) -> None:
        """Set the group's state; the day "Teach the agent" was used is kept."""
        rule = None if row.return_rule is None else row.return_rule.value
        with self._db:
            self._db.execute(
                "INSERT INTO triage (project, group_key, state, return_rule, after_sessions,"
                " changed_on) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (project, group_key) DO"
                " UPDATE SET state=excluded.state, return_rule=excluded.return_rule,"
                " after_sessions=excluded.after_sessions, changed_on=excluded.changed_on",
                (
                    project,
                    group_key,
                    row.state.value,
                    rule,
                    row.after_sessions,
                    row.changed_on.isoformat(),
                ),
            )

    def mark_taught(self, project: str, group_key: str, day: date) -> None:
        """Record the day "Teach the agent" was used; a group not yet triaged stays For review."""
        with self._db:
            self._db.execute(
                "INSERT INTO triage (project, group_key, state, changed_on, taught_on)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (project, group_key) DO UPDATE"
                " SET taught_on=excluded.taught_on",
                (project, group_key, GroupState.FOR_REVIEW.value, day.isoformat(), day.isoformat()),
            )

    def all(self, project: str) -> dict[str, TriageRow]:
        """Every saved group of `project`, by group key."""
        rows = self._db.execute(
            "SELECT group_key, state, return_rule, after_sessions, changed_on, taught_on"
            " FROM triage WHERE project=?",
            (project,),
        )
        return {key: _row_of(*rest) for key, *rest in rows}


def _row_of(
    state: str, rule: str | None, after: int | None, changed_on: str, taught_on: str | None
) -> TriageRow:
    """One stored row as a TriageRow; an unknown state or rule raises ValueError."""
    return TriageRow(
        GroupState(state),
        None if rule is None else ReturnRule(rule),
        after,
        date.fromisoformat(changed_on),
        None if taught_on is None else date.fromisoformat(taught_on),
    )
