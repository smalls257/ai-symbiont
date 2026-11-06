"""What mining kept, what it held back and why, and where files churned.

Held-back groups and churn are counts and names, never record text: the dashboard shows what was
not taught (struggle, with its cost) instead of dropping it quietly. Written in the same
transaction as the lessons, so the three never disagree about one mining run.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from symbiont.miner.churn import FileChurn
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.screen import HoldReason
from symbiont.miner.trained import refuse_held_out_lessons
from symbiont.store.lesson_rows import lesson_row

if TYPE_CHECKING:
    from symbiont.store.local import Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS held_back (
    project TEXT NOT NULL, reason TEXT NOT NULL, groups INTEGER NOT NULL,
    PRIMARY KEY (project, reason)
);
CREATE TABLE IF NOT EXISTS struggle (
    project TEXT NOT NULL, signal TEXT NOT NULL, key TEXT NOT NULL,
    sessions INTEGER NOT NULL, occurrences INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS churn (
    project TEXT NOT NULL, file TEXT NOT NULL, session_id TEXT NOT NULL, edits INTEGER NOT NULL
);
"""
# Plain words for the terminal and the dashboard; the reason's value is for storage only.
REASON_WORDS = {
    HoldReason.IGNORED: "set aside by you",
    HoldReason.NO_FIX_SHOWN: "no fix shown",
    HoldReason.NO_MESSAGE: "no message to tell them apart",
    HoldReason.PROBE_COMMAND: "look-around commands",
    HoldReason.TOO_FEW_SESSIONS: "seen in too few sessions",
}


@dataclass(frozen=True)
class StruggleGroup:
    """A kind of failure that never showed a fix: how widely and how often it happened."""

    signature: Signature
    sessions: int
    occurrences: int


@dataclass(frozen=True)
class MiningOutcome:
    """One mining run: the lessons that stay, and everything counted instead of taught."""

    kept: list[Lesson]
    held: dict[HoldReason, int] = field(default_factory=dict)
    struggle: list[Lesson] = field(default_factory=list)
    churn: list[FileChurn] = field(default_factory=list)


def struggle_groups(struggle: Sequence[Lesson]) -> list[StruggleGroup]:
    """Struggle lessons grouped by signature, the most widespread first."""
    grouped: dict[Signature, list[PainPoint]] = defaultdict(list)
    for lesson in struggle:
        grouped[lesson.pain_point.signature].append(lesson.pain_point)
    groups = [
        StruggleGroup(signature, len({p.session_id for p in points}), len(points))
        for signature, points in grouped.items()
    ]
    return sorted(
        groups, key=lambda group: (-group.sessions, -group.occurrences, group.signature.key)
    )


def held_back_sentence(held: Mapping[HoldReason, int]) -> str:
    """`held back 3: 2 no fix shown, 1 seen in too few sessions`; empty when nothing was held."""
    parts = [f"{held[reason]} {REASON_WORDS[reason]}" for reason in HoldReason if held.get(reason)]
    return f"held back {sum(held.values())}: " + ", ".join(parts) if parts else ""


def held_by_reason(held: Mapping[str, int]) -> dict[HoldReason, int]:
    """Counts keyed by the reason's stored value (as progress reports them) back to reasons."""
    return {reason: held[reason.value] for reason in HoldReason if held.get(reason.value)}


def _struggle_row(project: str, group: StruggleGroup) -> tuple[str, str, str, int, int]:
    """The struggle-table row for a group."""
    signature = group.signature
    key = json.dumps(signature.key)
    return (project, signature.signal.value, key, group.sessions, group.occurrences)


class MiningLedger:
    """Saving a mining run, and reading what it held back, struggled with and churned."""

    def __init__(self, db: sqlite3.Connection):
        """Wrap the store's connection."""
        self._db = db

    def save(
        self,
        project: str,
        new_sources: Iterable["Source"],
        outcome: MiningOutcome,
        *,
        held_out_tasks: frozenset[str],
    ) -> None:
        """Register `new_sources`, replace `project`'s lessons and what was held back, atomically.

        Raises HoldOutViolationError, writing nothing, when a lesson quotes a held-out task.
        """
        refuse_held_out_lessons(outcome.kept, held_out_tasks)
        db = self._db
        with db:
            db.executemany(
                "INSERT OR IGNORE INTO sources VALUES (?, ?, ?)",
                [(s.project, s.reader, s.path) for s in new_sources],
            )
            for table in ("lessons", "held_back", "struggle", "churn"):
                db.execute(f"DELETE FROM {table} WHERE project=?", (project,))  # noqa: S608
            db.executemany(
                "INSERT INTO lessons VALUES (?, ?, ?, ?, ?)",
                [lesson_row(project, lesson) for lesson in outcome.kept],
            )
            db.executemany(
                "INSERT INTO held_back VALUES (?, ?, ?)",
                [(project, reason.value, count) for reason, count in outcome.held.items()],
            )
            db.executemany(
                "INSERT INTO struggle VALUES (?, ?, ?, ?, ?)",
                [_struggle_row(project, group) for group in struggle_groups(outcome.struggle)],
            )
            db.executemany(
                "INSERT INTO churn VALUES (?, ?, ?, ?)",
                [(project, row.file, row.session_id, row.edits) for row in outcome.churn],
            )

    def counts(self, project: str) -> dict[HoldReason, int]:
        """Groups held per reason at the last mining; reasons that held nothing are absent."""
        rows = self._db.execute("SELECT reason, groups FROM held_back WHERE project=?", (project,))
        saved = dict(rows.fetchall())
        return {reason: saved[reason.value] for reason in HoldReason if reason.value in saved}

    def struggle(self, project: str) -> list[StruggleGroup]:
        """The failure groups with no shown fix, widest first."""
        rows = self._db.execute(
            "SELECT signal, key, sessions, occurrences FROM struggle WHERE project=? "
            "ORDER BY sessions DESC, occurrences DESC, rowid",
            (project,),
        ).fetchall()
        return [
            StruggleGroup(Signature(Signal(signal), tuple(json.loads(key))), sessions, occurrences)
            for signal, key, sessions, occurrences in rows
        ]

    def churn(self, project: str) -> list[FileChurn]:
        """Edits per file per session, from the last mining."""
        rows = self._db.execute(
            "SELECT file, session_id, edits FROM churn WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        return [FileChurn(file, session_id, edits) for file, session_id, edits in rows]
