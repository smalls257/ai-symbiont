"""The facts kept per session and the few strips drawn, in the same database as the lessons.

Facts are themes, pattern names, counts and a short scrubbed task label: no output, no quotes.
Written in the transaction of the lessons they came from, so the dashboard never shows facts of
one mining beside lessons of another.
"""

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from symbiont.miner.patterns import StrugglePattern
from symbiont.miner.strips import Lane, SessionStrip, StripStep
from symbiont.miner.struggle import SessionFacts

TABLES = ("session_facts", "session_strips")
SCHEMA = """
CREATE TABLE IF NOT EXISTS session_facts (
    project TEXT NOT NULL, session_id TEXT NOT NULL, task_label TEXT NOT NULL,
    themes TEXT NOT NULL, patterns TEXT NOT NULL, turns_lost INTEGER NOT NULL,
    outcomes TEXT NOT NULL, struggled INTEGER NOT NULL, started TEXT
);
CREATE TABLE IF NOT EXISTS session_strips (
    project TEXT NOT NULL, session_id TEXT NOT NULL, task_label TEXT NOT NULL,
    burst INTEGER NOT NULL, steps TEXT NOT NULL, total_steps INTEGER NOT NULL
);
"""


def add_missing_started(db: sqlite3.Connection) -> None:
    """Add `session_facts.started` to stores mined before sessions carried a start day.

    Their sessions read as undated until the next mining rewrites the facts.
    """
    if _has_started(db):
        return
    db.execute("BEGIN IMMEDIATE")  # a second process opening the same old store waits here
    try:
        if not _has_started(db):  # re-checked inside the lock: the other process may have won
            db.execute("ALTER TABLE session_facts ADD COLUMN started TEXT")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _has_started(db: sqlite3.Connection) -> bool:
    return "started" in {row[1] for row in db.execute("PRAGMA table_info(session_facts)")}


def insert_struggle(
    db: sqlite3.Connection,
    project: str,
    facts: Sequence[SessionFacts],
    strips: Sequence[SessionStrip],
) -> None:
    """Add one mining's facts and strips; the caller deleted the old ones in its transaction."""
    db.executemany(
        "INSERT INTO session_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [_fact_row(project, fact) for fact in facts],
    )
    db.executemany(
        "INSERT INTO session_strips VALUES (?, ?, ?, ?, ?, ?)",
        [_strip_row(project, strip) for strip in strips],
    )


_FactRow = tuple[str, str, str, str, str, int, str, int, str | None]


def _fact_row(project: str, fact: SessionFacts) -> _FactRow:
    return (
        project,
        fact.session_id,
        fact.task_label,
        json.dumps(sorted(fact.themes)),
        json.dumps(sorted(fact.patterns)),
        fact.turns_lost,
        json.dumps(dict(fact.outcomes)),
        int(fact.struggled),
        fact.started,
    )


def _strip_row(project: str, strip: SessionStrip) -> tuple[str, str, str, int, str, int]:
    steps = [[s.step, s.lane.value, s.label] for s in strip.steps]
    return (
        project,
        strip.session_id,
        strip.task_label,
        strip.burst,
        json.dumps({"offset": strip.offset, "steps": steps}),
        strip.total_steps,
    )


def read_facts(db: sqlite3.Connection, project: str) -> list[SessionFacts]:
    """The facts of the last mining, in the order the sessions were mined."""
    rows = db.execute(
        "SELECT session_id, task_label, themes, patterns, turns_lost, outcomes, struggled, started "
        "FROM session_facts WHERE project=? ORDER BY rowid",
        (project,),
    ).fetchall()
    return [
        SessionFacts(
            sid,
            label,
            frozenset(json.loads(themes)),
            frozenset(StrugglePattern(p) for p in json.loads(patterns)),
            turns,
            json.loads(outcomes),
            bool(struggled),
            started,
        )
        for sid, label, themes, patterns, turns, outcomes, struggled, started in rows
    ]


def read_strips(db: sqlite3.Connection, project: str) -> list[SessionStrip]:
    """The strips of the last mining."""
    rows = db.execute(
        "SELECT session_id, task_label, burst, steps, total_steps FROM session_strips "
        "WHERE project=? ORDER BY rowid",
        (project,),
    ).fetchall()
    return [
        SessionStrip(sid, label, burst, _steps_from(steps), total, _offset_of(steps))
        for sid, label, burst, steps, total in rows
    ]


def _listed(body: str) -> list[list[Any]]:
    """The steps in a stored strip; a strip stored before windows is the bare list."""
    stored = json.loads(body)
    steps: list[list[Any]] = stored["steps"] if isinstance(stored, dict) else stored
    return steps


def _offset_of(body: str) -> int:
    """How many drawn steps precede the stored window; 0 for a strip stored before windows."""
    stored = json.loads(body)
    return int(stored["offset"]) if isinstance(stored, dict) else 0


def _steps_from(body: str) -> tuple[StripStep, ...]:
    return tuple(StripStep(int(n), Lane(lane), str(name)) for n, lane, name in _listed(body))
