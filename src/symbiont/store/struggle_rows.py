"""The facts kept per session and the few strips drawn, in the same database as the lessons.

Facts are themes, pattern names, counts and a short scrubbed task label: no output, no quotes.
Written in the transaction of the lessons they came from, so the dashboard never shows facts of
one mining beside lessons of another.
"""

import json
import sqlite3
from collections.abc import Sequence

from symbiont.miner.patterns import StrugglePattern
from symbiont.miner.strips import Lane, SessionStrip, StripStep
from symbiont.miner.struggle import SessionFacts

TABLES = ("session_facts", "session_strips")
SCHEMA = """
CREATE TABLE IF NOT EXISTS session_facts (
    project TEXT NOT NULL, session_id TEXT NOT NULL, task_label TEXT NOT NULL,
    themes TEXT NOT NULL, patterns TEXT NOT NULL, turns_lost INTEGER NOT NULL,
    outcomes TEXT NOT NULL, struggled INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS session_strips (
    project TEXT NOT NULL, session_id TEXT NOT NULL, task_label TEXT NOT NULL,
    burst INTEGER NOT NULL, steps TEXT NOT NULL
);
"""


def insert_struggle(
    db: sqlite3.Connection,
    project: str,
    facts: Sequence[SessionFacts],
    strips: Sequence[SessionStrip],
) -> None:
    """Add one mining's facts and strips; the caller deleted the old ones in its transaction."""
    db.executemany(
        "INSERT INTO session_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [_fact_row(project, fact) for fact in facts],
    )
    db.executemany(
        "INSERT INTO session_strips VALUES (?, ?, ?, ?, ?)",
        [_strip_row(project, strip) for strip in strips],
    )


def _fact_row(project: str, fact: SessionFacts) -> tuple[str, str, str, str, str, int, str, int]:
    return (
        project,
        fact.session_id,
        fact.task_label,
        json.dumps(sorted(fact.themes)),
        json.dumps(sorted(fact.patterns)),
        fact.turns_lost,
        json.dumps(dict(fact.outcomes)),
        int(fact.struggled),
    )


def _strip_row(project: str, strip: SessionStrip) -> tuple[str, str, str, int, str]:
    steps = [[s.step, s.lane.value, s.label] for s in strip.steps]
    return (project, strip.session_id, strip.task_label, strip.burst, json.dumps(steps))


def read_facts(db: sqlite3.Connection, project: str) -> list[SessionFacts]:
    """The facts of the last mining, in the order the sessions were mined."""
    rows = db.execute(
        "SELECT session_id, task_label, themes, patterns, turns_lost, outcomes, struggled "
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
        )
        for sid, label, themes, patterns, turns, outcomes, struggled in rows
    ]


def read_strips(db: sqlite3.Connection, project: str) -> list[SessionStrip]:
    """The strips of the last mining."""
    rows = db.execute(
        "SELECT session_id, task_label, burst, steps FROM session_strips "
        "WHERE project=? ORDER BY rowid",
        (project,),
    ).fetchall()
    return [
        SessionStrip(
            sid,
            label,
            burst,
            tuple(StripStep(n, Lane(lane), name) for n, lane, name in json.loads(steps)),
        )
        for sid, label, burst, steps in rows
    ]
