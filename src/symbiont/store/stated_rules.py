"""The standing rules the session's model confirmed, and the candidates it set aside.

Developer-owned like summaries: NOT in `REPLACED_TABLES`, because a re-mine that emptied them
would make the model, and the developer who pays for it, judge every candidate again. A rule's
key is `rule:` plus its smallest ref, so a rule finds its candidates again after a re-mine.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date

from symbiont.miner.stated_rule import Ref, RuleScope, StatedRule

SCHEMA = """
CREATE TABLE IF NOT EXISTS stated_rules (
    project TEXT NOT NULL, key TEXT NOT NULL, rule TEXT NOT NULL, scope TEXT NOT NULL,
    area TEXT NOT NULL, refs TEXT NOT NULL, written_on TEXT NOT NULL,
    PRIMARY KEY (project, key)
);
CREATE TABLE IF NOT EXISTS dropped_rule_candidates (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    PRIMARY KEY (project, session_id, step)
);
"""


class StatedRules:
    """Reads and writes the stated_rules tables of an open store connection."""

    def __init__(self, db: sqlite3.Connection) -> None:
        """Use the store's connection."""
        self._db = db

    def save(
        self, project: str, rules: Sequence[StatedRule], dropped: Iterable[Ref], day: date
    ) -> None:
        """Keep the rules and the dropped refs in one transaction; the same key replaces."""
        rows = [
            (project, r.key, r.rule, r.scope.value, r.area, json.dumps(r.refs), day.isoformat())
            for r in rules
        ]
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO stated_rules VALUES (?,?,?,?,?,?,?)", rows)
            self._db.executemany(
                "INSERT OR IGNORE INTO dropped_rule_candidates VALUES (?,?,?)",
                [(project, session_id, step) for session_id, step in dropped],
            )

    def rules(self, project: str) -> list[StatedRule]:
        """Every rule of `project`, oldest first."""
        rows = self._db.execute(
            "SELECT rule, scope, area, refs FROM stated_rules WHERE project=? "
            "ORDER BY written_on, key",
            (project,),
        )
        return [
            StatedRule(rule, RuleScope(scope), area, tuple((s, n) for s, n in json.loads(refs)))
            for rule, scope, area, refs in rows
        ]

    def covered(self, project: str) -> frozenset[Ref]:
        """The candidates a saved rule merged plus those judged not to be rules."""
        covered = {ref for rule in self.rules(project) for ref in rule.refs}
        rows = self._db.execute(
            "SELECT session_id, step FROM dropped_rule_candidates WHERE project=?", (project,)
        )
        return frozenset(covered | {(session_id, step) for session_id, step in rows})
