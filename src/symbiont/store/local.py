"""Local SQLite store of records and mined pain points, with two guards.

- Hold-out: a scored task's trajectory must never enter a store a scored arm
  reads, or `recall` could surface a near-gold patch. `add_records` takes the
  held-out task ids as a required argument and raises `HoldOutViolationError`
  naming the task before writing anything from the batch. Ids are compared
  after normalising the benchmark spellings (`owner__repo-123`,
  `owner/repo#123`); an id in neither spelling raises `UnrecognisedTaskIdError`
  rather than silently matching nothing. Records with no task id cannot be matched and are
  accepted (the developer's own sessions); the caller states the set per
  batch, so it can differ for external history and an arm's own sessions.
- Spark: `spark_view()` is a read-only view for anything bound for Spark.
  Any read that would return a record with `spark_safe=False` (SWE-chat,
  private sessions), or a pain point citing one, raises
  `SparkPrivacyViolationError`. It never filters quietly: a filtered view would
  make a privacy bug look like "no history".
"""

import io
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from symbiont.miner.mine import mine_chain
from symbiont.miner.painpoint import PainPoint, RecordRef, Signal, Signature
from symbiont.records.holdout import HoldOutViolationError, normalise_task_id
from symbiont.records.schema import Record, dump_jsonl, load_jsonl

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    harness TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    project TEXT NOT NULL, task_id TEXT, spark_safe INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (harness, session_id, step)
);
CREATE TABLE IF NOT EXISTS pain_points (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL, body TEXT NOT NULL
);
-- Pain points cite records by (session_id, step); the primary key starts with
-- harness, so without this every lookup would scan the table.
CREATE INDEX IF NOT EXISTS records_by_ref ON records (session_id, step);
CREATE INDEX IF NOT EXISTS records_by_project ON records (project, spark_safe);
CREATE INDEX IF NOT EXISTS pain_points_by_project ON pain_points (project);
"""


class SparkPrivacyViolationError(PermissionError):
    """A read would hand a not-Spark-safe record to a Spark-bound prompt."""

    def __init__(self, record: Record):
        super().__init__(
            f"record {record.session_id}:{record.step} comes from {record.provenance.dataset}, "
            "which is not Spark-safe; it must not reach a Spark-bound prompt"
        )
        self.record = record


class StoreConflictError(ValueError):
    """A record differs from the one already stored under the same key."""


class Store:
    """SQLite-backed records and pain points; the only persistence the rest of the system sees."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "Store":
        """Open (creating if needed) the store at `path`."""
        db = sqlite3.connect(path)
        db.executescript(_SCHEMA)
        return cls(db)

    def add_records(self, records: Iterable[Record], *, held_out_tasks: frozenset[str]) -> int:
        """Return how many records were new.

        Raises before writing anything if any record belongs to a held-out task
        or conflicts with a stored one.
        """
        batch = list(records)
        _check_held_out(batch, held_out_tasks)
        added = 0
        with self._db:
            for record in batch:
                added += self._insert(record)
        return added

    def _insert(self, record: Record) -> int:
        body = _record_json(record)
        key = (record.harness, record.session_id, record.step)
        row = self._db.execute(
            "SELECT body FROM records WHERE harness=? AND session_id=? AND step=?", key
        ).fetchone()
        if row is not None:
            if row[0] != body:
                raise StoreConflictError(
                    f"{record.harness} session {record.session_id} step {record.step} "
                    "is already stored with different content"
                )
            return 0
        self._db.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)",
            (*key, record.project, record.task_id, record.provenance.spark_safe, body),
        )
        return 1

    def mine(self, project: str, *, references: Mapping[str, frozenset[str]]) -> int:
        """Re-mine every session of `project`, replacing its pain points.

        `references` as for blast radius; `{}` when there is no checkout.

        Sessions with timestamps form one chain in the order they started (a
        developer's history on this repo, so rework across sessions counts).
        Sessions without any timestamp have no known order; published
        trajectories are parallel attempts at the same tasks, so each is
        mined alone. ISO 8601 timestamps in one timezone are assumed.
        """
        timed, untimed = _chains(self.sessions(project))
        found = mine_chain(timed, references)
        found += [p for session in untimed for p in mine_chain([session], references)]
        with self._db:
            self._db.execute("DELETE FROM pain_points WHERE project=?", (project,))
            self._db.executemany(
                "INSERT INTO pain_points VALUES (?, ?, ?, ?)",
                [(project, p.session_id, p.step, _pain_point_json(p)) for p in found],
            )
        return len(found)

    def sessions(self, project: str) -> list[list[Record]]:
        """Every session of `project`, each in step order."""
        rows = self._db.execute(
            "SELECT harness, session_id, body FROM records WHERE project=? "
            "ORDER BY harness, session_id, step",
            (project,),
        ).fetchall()
        grouped: dict[tuple[str, str], list[Record]] = {}
        for harness, session_id, body in rows:
            grouped.setdefault((harness, session_id), []).append(_record_from_json(body))
        return list(grouped.values())

    def pain_points(self, project: str) -> list[PainPoint]:
        """The mined pain points of `project`, in the order they were mined."""
        rows = self._db.execute(
            "SELECT body FROM pain_points WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        return [_pain_point_from_json(body) for (body,) in rows]

    def records_for(self, refs: Iterable[RecordRef]) -> list[Record]:
        """The records the refs cite; a ref with no record, or two, raises LookupError."""
        found = []
        for session_id, step in refs:
            rows = self._db.execute(
                "SELECT body FROM records WHERE session_id=? AND step=?", (session_id, step)
            ).fetchall()
            if len(rows) != 1:
                problem = "no record" if not rows else "more than one record (two harnesses?)"
                raise LookupError(f"{problem} for session {session_id!r} step {step}")
            found.append(_record_from_json(rows[0][0]))
        return found

    def private_refs(self, project: str) -> frozenset[RecordRef]:
        """(session_id, step) of every record in `project` that is not Spark-safe."""
        rows = self._db.execute(
            "SELECT session_id, step FROM records WHERE project=? AND spark_safe=0", (project,)
        ).fetchall()
        return frozenset((session_id, step) for session_id, step in rows)

    def spark_view(self) -> "SparkView":
        """A read-only view that raises rather than return anything not Spark-safe."""
        return SparkView(self)


class SparkView:
    """Read-only; every read raises rather than return a private record."""

    def __init__(self, store: Store):
        self._store = store

    def sessions(self, project: str) -> list[list[Record]]:
        """Sessions of `project`, or SparkPrivacyViolationError if any record is private."""
        found = self._store.sessions(project)
        _refuse_private(r for s in found for r in s)
        return found

    def pain_points(self, project: str) -> list[PainPoint]:
        """Pain points of `project`, or SparkPrivacyViolationError if one cites a private record."""
        found = self._store.pain_points(project)
        private = self._store.private_refs(project)
        cited = next((ref for p in found for ref in p.record_refs if ref in private), None)
        if cited is not None:
            _refuse_private(self._store.records_for([cited]))
        return found

    def records_for(self, refs: Iterable[RecordRef]) -> list[Record]:
        """Cited records, or SparkPrivacyViolationError if any is private."""
        found = self._store.records_for(refs)
        _refuse_private(found)
        return found


def _chains(sessions: list[list[Record]]) -> tuple[list[list[Record]], list[list[Record]]]:
    """Split into (timed sessions in start order, untimed sessions)."""
    timed = [(start, s) for s in sessions if (start := _started(s)) is not None]
    untimed = [s for s in sessions if _started(s) is None]
    return [s for _, s in sorted(timed, key=lambda pair: pair[0])], untimed


def _started(session: list[Record]) -> str | None:
    return min((r.ts for r in session if r.ts is not None), default=None)


def _refuse_private(records: Iterable[Record]) -> None:
    for record in records:
        if not record.provenance.spark_safe:
            raise SparkPrivacyViolationError(record)


def _check_held_out(records: Sequence[Record], held_out_tasks: frozenset[str]) -> None:
    """Refuse a batch containing a held-out task.

    With nothing held out, task ids are free-form (the developer's own
    projects). Otherwise every id on both sides must be a benchmark id.
    """
    held_out = {normalise_task_id(t) for t in held_out_tasks}
    if not held_out:
        return
    for record in records:
        if record.task_id is not None and normalise_task_id(record.task_id) in held_out:
            raise HoldOutViolationError(record.task_id, record.session_id)


# --- serialisation -------------------------------------------------------------


def _record_json(record: Record) -> str:
    out = io.StringIO()
    dump_jsonl([record], out)
    return out.getvalue().rstrip("\n")


def _record_from_json(body: str) -> Record:
    (record,) = load_jsonl(io.StringIO(body))
    return record


def _pain_point_json(pain: PainPoint) -> str:
    return json.dumps(asdict(pain))


def _pain_point_from_json(body: str) -> PainPoint:
    data = json.loads(body)
    signature = data["signature"]
    return PainPoint(
        signature=Signature(Signal(signature["signal"]), tuple(signature["key"])),
        session_id=data["session_id"],
        step=data["step"],
        record_refs=tuple((ref[0], ref[1]) for ref in data["record_refs"]),
    )
