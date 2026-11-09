"""The developer's review status of each failure group, kept across re-mines.

Triage is developer-owned state like `ignored`, so it is
NOT in `REPLACED_TABLES`: a re-mine rebuilds the groups but never forgets which were Resolved.
`group_key` is the opaque fingerprint of a failure group; this table treats it as text.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from symbiont.core.triage import GroupState, ReturnRule, TriageRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS triage (
    project TEXT NOT NULL, group_key TEXT NOT NULL, state TEXT NOT NULL,
    return_rule TEXT, after_sessions INTEGER, changed_on TEXT NOT NULL, taught_on TEXT,
    name TEXT NOT NULL DEFAULT '', until TEXT, lesson_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project, group_key)
);
CREATE TABLE IF NOT EXISTS rule_triage_members (
    project TEXT NOT NULL, key TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    PRIMARY KEY (project, key, session_id, step)
);
"""
Ref = tuple[str, int]


@dataclass(frozen=True)
class RuleTeach:
    """A teach: its day, the lesson it stored, and the rule messages it stands for."""

    day: date
    lesson_id: str = ""
    members: tuple[Ref, ...] = ()


def _remember_members(db: sqlite3.Connection, project: str, key: str, refs: Iterable[Ref]) -> None:
    """Keep the messages a triaged rule stood for, inside the caller's transaction.

    Grouping can rename a rule when an earlier session is mined; the dismissal follows the words.
    """
    db.executemany(
        "INSERT OR IGNORE INTO rule_triage_members VALUES (?,?,?,?)",
        [(project, key, session_id, step) for session_id, step in refs],
    )


def add_missing_name(db: sqlite3.Connection) -> None:
    """Give a store from before group names the `name` column, once, when it is opened."""
    if "name" not in {column[1] for column in db.execute("PRAGMA table_info(triage)")}:
        with db:
            db.execute("ALTER TABLE triage ADD COLUMN name TEXT NOT NULL DEFAULT ''")


def add_missing_until(db: sqlite3.Connection) -> None:
    """Give a store from before "For 30 days" the `until` column, once, when it is opened."""
    if "until" not in {column[1] for column in db.execute("PRAGMA table_info(triage)")}:
        with db:
            db.execute("ALTER TABLE triage ADD COLUMN until TEXT")


def add_missing_lesson_id(db: sqlite3.Connection) -> None:
    """Give a store from before lesson ids were kept the `lesson_id` column, once, when opened."""
    if "lesson_id" not in {column[1] for column in db.execute("PRAGMA table_info(triage)")}:
        with db:
            db.execute("ALTER TABLE triage ADD COLUMN lesson_id TEXT NOT NULL DEFAULT ''")


class GroupTriage:
    """Reads and writes the triage table of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def rename(self, project: str, group_key: str, name: str, day: date) -> None:
        """Keep the developer's name for a group; "" restores the generated name.

        The name lives on the triage row, which a re-mine never replaces, so it outlives re-mines.
        A group not yet triaged stays For review.
        """
        with self._db:
            self._db.execute(
                "INSERT INTO triage (project, group_key, state, changed_on, name)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (project, group_key) DO"
                " UPDATE SET name=excluded.name",
                (project, group_key, GroupState.FOR_REVIEW.value, day.isoformat(), name),
            )

    def names(self, project: str) -> dict[str, str]:
        """The developer's names for groups of `project`, by group key; unnamed ones are absent."""
        rows = self._db.execute(
            "SELECT group_key, name FROM triage WHERE project=? AND name != ''", (project,)
        )
        return dict(rows)

    def save(
        self, project: str, group_key: str, row: TriageRow, members: Iterable[Ref] = ()
    ) -> None:
        """Set the group's state, with the rule messages it stands for; the taught day is kept."""
        rule = None if row.return_rule is None else row.return_rule.value
        with self._db:
            _remember_members(self._db, project, group_key, members)
            self._db.execute(
                "INSERT INTO triage (project, group_key, state, return_rule, after_sessions,"
                " changed_on, until) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (project, group_key) DO UPDATE SET state=excluded.state,"
                " return_rule=excluded.return_rule,"
                " after_sessions=excluded.after_sessions, changed_on=excluded.changed_on,"
                " until=excluded.until",
                (
                    project,
                    group_key,
                    row.state.value,
                    rule,
                    row.after_sessions,
                    row.changed_on.isoformat(),
                    _text_of(row.until),
                ),
            )

    def mark_taught(self, project: str, group_key: str, day: date, lesson_id: str = "") -> None:
        """Record the day "Teach the agent" was used and the id of the lesson it stored.

        A teach with no id keeps the id already there. A group not yet triaged stays For review.
        """
        self.mark_rule_taught(project, group_key, RuleTeach(day, lesson_id))

    def mark_rule_taught(self, project: str, group_key: str, teach: "RuleTeach") -> None:
        """`mark_taught` plus the rule messages it stands for, in one transaction."""
        with self._db:
            _remember_members(self._db, project, group_key, teach.members)
            self._db.execute(
                "INSERT INTO triage (project, group_key, state, changed_on, taught_on, lesson_id)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (project, group_key) DO UPDATE"
                " SET taught_on=excluded.taught_on, lesson_id=CASE WHEN excluded.lesson_id != ''"
                " THEN excluded.lesson_id ELSE triage.lesson_id END",
                (
                    project,
                    group_key,
                    GroupState.FOR_REVIEW.value,
                    teach.day.isoformat(),
                    teach.day.isoformat(),
                    teach.lesson_id,
                ),
            )

    def lesson_ids(self, project: str) -> dict[str, str]:
        """The id of the lesson each taught group stored, by group key; none known is absent."""
        rows = self._db.execute(
            "SELECT group_key, lesson_id FROM triage WHERE project=? AND lesson_id != ''",
            (project,),
        )
        return dict(rows)

    def members_by_key(self, project: str) -> dict[str, frozenset[Ref]]:
        """The remembered rule messages of each triaged rule key."""
        found: dict[str, set[Ref]] = {}
        rows = self._db.execute(
            "SELECT key, session_id, step FROM rule_triage_members WHERE project=?", (project,)
        )
        for key, session_id, step in rows:
            found.setdefault(key, set()).add((session_id, step))
        return {key: frozenset(refs) for key, refs in found.items()}

    def all(self, project: str) -> dict[str, TriageRow]:
        """Every saved group of `project`, by group key."""
        rows = self._db.execute(
            "SELECT group_key, state, return_rule, after_sessions, changed_on, taught_on, until"
            " FROM triage WHERE project=?",
            (project,),
        )
        return {
            key: _row_of(state, rule, after, (changed, taught, until))
            for key, state, rule, after, changed, taught, until in rows
        }


def _text_of(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _row_of(
    state: str, rule: str | None, after: int | None, days: tuple[str, str | None, str | None]
) -> TriageRow:
    """One stored row as a TriageRow; days are (changed_on, taught_on, until) as ISO text.

    An unknown state or rule raises ValueError.
    """
    changed_on, taught_on, until = days
    return TriageRow(
        GroupState(state),
        None if rule is None else ReturnRule(rule),
        after,
        date.fromisoformat(changed_on),
        None if taught_on is None else date.fromisoformat(taught_on),
        None if until is None else date.fromisoformat(until),
    )
