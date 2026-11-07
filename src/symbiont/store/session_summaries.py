"""Session summaries and the topic map, kept in the store beside the lessons.

They are the developer's session model's work, written once per session and paid for in
requests, so a re-mine must keep them: these tables are not in `held_back.REPLACED_TABLES`, or
a re-mine would quietly empty them and bill the developer again. Like ignored patterns they are
developer-owned state. They hold the model's words (goal, friction, names), never record text.
"""

import json
import sqlite3
from collections.abc import Sequence

from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.topics import CorrectionGroup, Group, TopicMap

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_summaries (
    project TEXT NOT NULL, session_id TEXT NOT NULL, goal TEXT NOT NULL, outcome TEXT NOT NULL,
    friction TEXT NOT NULL, noise INTEGER NOT NULL,
    PRIMARY KEY (project, session_id)
);
CREATE TABLE IF NOT EXISTS topics (
    project TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
    members TEXT NOT NULL
);
"""
TOPIC, FRICTION, CORRECTION_GROUP = "topic", "friction", "correction_group"


class SessionSummaries:
    """Reads and writes the session_summaries and topics tables of a store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(self, project: str, summaries: Sequence[SessionSummary]) -> None:
        """Keep the summaries; one written again for the same session replaces the earlier."""
        rows = [
            (project, s.session_id, s.goal, s.outcome.value, s.friction, int(s.noise))
            for s in summaries
        ]
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO session_summaries VALUES (?,?,?,?,?,?)", rows
            )

    def summarized(self, project: str) -> frozenset[str]:
        """The ids of the sessions that have a summary."""
        rows = self._db.execute(
            "SELECT session_id FROM session_summaries WHERE project=?", (project,)
        )
        return frozenset(row[0] for row in rows)

    def all(self, project: str) -> list[SessionSummary]:
        """Every summary of `project`, newest write first."""
        rows = self._db.execute(
            "SELECT session_id, goal, outcome, friction, noise FROM session_summaries "
            "WHERE project=? ORDER BY rowid DESC",
            (project,),
        )
        return [SessionSummary(i, g, SummaryOutcome(o), f, bool(n)) for i, g, o, f, n in rows]

    def save_topics(self, project: str, topic_map: TopicMap) -> None:
        """Replace the project's topic map as a whole, in one transaction."""
        rows = [
            *(_row(project, TOPIC, g, list(g.session_ids)) for g in topic_map.topics),
            *(_row(project, FRICTION, g, list(g.session_ids)) for g in topic_map.frictions),
            *(
                _row(project, CORRECTION_GROUP, g, [list(ref) for ref in g.refs])
                for g in topic_map.correction_groups
            ),
        ]
        with self._db:
            self._db.execute("DELETE FROM topics WHERE project=?", (project,))
            self._db.executemany("INSERT INTO topics VALUES (?,?,?,?,?)", rows)

    def topics(self, project: str) -> TopicMap:
        """The saved topic map; empty when none was saved."""
        rows = self._db.execute(
            "SELECT kind, name, description, members FROM topics WHERE project=? ORDER BY rowid",
            (project,),
        ).fetchall()
        return TopicMap(
            tuple(_group(r) for r in rows if r[0] == TOPIC),
            tuple(_group(r) for r in rows if r[0] == FRICTION),
            tuple(_correction_group(r) for r in rows if r[0] == CORRECTION_GROUP),
        )


def _row(
    project: str, kind: str, group: Group | CorrectionGroup, members: list[object]
) -> tuple[str, ...]:
    return (project, kind, group.name, group.description, json.dumps(members))


def _group(row: tuple[str, str, str, str]) -> Group:
    return Group(row[1], row[2], tuple(json.loads(row[3])))


def _correction_group(row: tuple[str, str, str, str]) -> CorrectionGroup:
    refs = tuple((session, step) for session, step in json.loads(row[3]))
    return CorrectionGroup(row[1], row[2], refs)
