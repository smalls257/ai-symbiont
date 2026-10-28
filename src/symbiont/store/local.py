"""Local SQLite store of mined lessons and of where each project's history lives. No raw history.

Memory is the personal model's weights (owner decision 2026-10-28), so the store
keeps no record rows: the harness's logs stay where the harness wrote them and
are re-read through the readers each time a project is mined (`store.mining`).
What is kept:

- Sources: (project, reader, path) pointers to those logs, never their contents.
- Lessons: each pain point with its own short quote, resolution, privacy flag and
  the (session, step) ids it came from, until training consumes them;
  `forget_trained` deletes them after writing a manifest of ids and counts.

Guards:

- Hold-out: checked at mining time, before a lesson is stored (`store.mining`).
- Spark: `spark_view()` is a read-only view for anything bound for Spark. A read
  that would return a lesson whose flag is false raises
  `SparkPrivacyViolationError`. It never filters quietly: a filtered view would
  make a privacy bug look like "no history".
"""

import json
import logging
import shlex
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.miner.trained import lesson_id, refuse_held_out_lessons, training_manifest

log = logging.getLogger("symbiont.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    project TEXT NOT NULL, reader TEXT NOT NULL, path TEXT NOT NULL,
    PRIMARY KEY (project, reader, path)
);
CREATE TABLE IF NOT EXISTS lessons (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    spark_safe INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_by_project ON lessons (project, spark_safe);
-- Ids (no text) of lessons a model was trained on, with the export that carried them.
CREATE TABLE IF NOT EXISTS trained (
    project TEXT NOT NULL, lesson_id TEXT NOT NULL, export_id TEXT NOT NULL,
    PRIMARY KEY (project, lesson_id)
);
"""
_DELETE_ONE = "DELETE FROM lessons WHERE project=? AND body=?"
# Tables an older version filled with copied history; read by nothing now.
_LEGACY_TABLES = ("records", "pain_points")


class SparkPrivacyViolationError(PermissionError):
    """A read would hand a lesson that is not Spark-safe to a Spark-bound prompt."""

    def __init__(self, project: str, what: str):
        super().__init__(
            f"{what} in project {project!r} is not Spark-safe; "
            "it must not reach a Spark-bound prompt"
        )
        self.project = project


@dataclass(frozen=True)
class Source:
    """Where some of a project's history lives: a harness log and the reader that parses it."""

    project: str
    reader: str
    path: str


class Store:
    """Lessons and source pointers; the only persistence the rest of the system sees."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "Store":
        """Open (creating if needed) the store at `path`."""
        # The threaded service shares one store; it serializes every call under its own lock.
        db = sqlite3.connect(path, check_same_thread=False)
        db.executescript(_SCHEMA)
        _warn_about_legacy_history(db, path)
        return cls(db)

    def sources(self, project: str) -> list[Source]:
        """Every log registered for `project`, in the order it was added."""
        rows = self._db.execute(
            "SELECT reader, path FROM sources WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        return [Source(project, reader, path) for reader, path in rows]

    def save_mining(
        self,
        project: str,
        new_sources: Iterable[Source],
        lessons: Sequence[Lesson],
        *,
        held_out_tasks: frozenset[str],
    ) -> None:
        """Register `new_sources` and replace `project`'s lessons, in one transaction.

        Raises HoldOutViolationError, writing nothing, when a lesson quotes a held-out task.
        """
        refuse_held_out_lessons(lessons, held_out_tasks)
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO sources VALUES (?, ?, ?)",
                [(s.project, s.reader, s.path) for s in new_sources],
            )
            self._db.execute("DELETE FROM lessons WHERE project=?", (project,))
            self._db.executemany(
                "INSERT INTO lessons VALUES (?, ?, ?, ?, ?)",
                [_lesson_row(project, lesson) for lesson in lessons],
            )

    def lessons(self, project: str) -> list[Lesson]:
        """The stored lessons of `project`, in the order they were mined."""
        rows = self._db.execute(
            "SELECT body FROM lessons WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        return [_lesson_from_json(body) for (body,) in rows]

    def pain_points(self, project: str) -> list[PainPoint]:
        """The pain points behind `project`'s lessons, in the order they were mined."""
        return [lesson.pain_point for lesson in self.lessons(project)]

    def forget_trained(
        self, project: str, manifest_path: Path, *, exported: Sequence[Lesson]
    ) -> int:
        """Delete the `exported` lessons of `project` once a model was trained on them.

        First writes the training manifest (export id, lesson ids, source sessions,
        task ids, counts; no text) to `manifest_path`, so a scored run can still prove
        no held-out trajectory trained the model, and remembers the lesson ids so the
        memory-model export never offers them again. An existing manifest is never
        overwritten, and if writing fails nothing is deleted. Returns how many were deleted.
        """
        manifest = training_manifest(project, exported)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8") as out:
            json.dump(manifest, out, indent=1)
        with self._db:
            deleted = sum(
                self._db.execute(
                    "DELETE FROM lessons WHERE project=? AND body=?",
                    (project, _lesson_json(lesson)),
                ).rowcount
                for lesson in exported
            )
            self._db.executemany(
                "INSERT OR REPLACE INTO trained VALUES (?, ?, ?)",
                [(project, lesson_id(lesson), manifest["export_id"]) for lesson in exported],
            )
        log.info("deleted %d trained lessons of %s; manifest %s", deleted, project, manifest_path)
        return deleted

    def trained_lesson_ids(self, project: str) -> frozenset[str]:
        """Ids of `project`'s lessons a model has already been trained on."""
        rows = self._db.execute("SELECT lesson_id FROM trained WHERE project=?", (project,))
        return frozenset(row[0] for row in rows)

    def has_private_lessons(self, project: str) -> bool:
        """True when any lesson of `project` came from a record that is not Spark-safe."""
        row = self._db.execute(
            "SELECT 1 FROM lessons WHERE project=? AND spark_safe=0 LIMIT 1", (project,)
        ).fetchone()
        return row is not None

    def spark_view(self) -> "SparkView":
        """A read-only view that raises rather than return anything not Spark-safe."""
        return SparkView(self)


class SparkView:
    """Read-only; every read raises rather than return a private lesson."""

    def __init__(self, store: Store):
        self._store = store

    def lessons(self, project: str) -> list[Lesson]:
        """Lessons of `project`, or SparkPrivacyViolationError if any is private."""
        if self._store.has_private_lessons(project):
            raise SparkPrivacyViolationError(project, "a lesson")
        return self._store.lessons(project)

    def pain_points(self, project: str) -> list[PainPoint]:
        """Pain points of `project`, or SparkPrivacyViolationError if any lesson is private."""
        return [lesson.pain_point for lesson in self.lessons(project)]


def _warn_about_legacy_history(db: sqlite3.Connection, path: Path) -> None:
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    legacy = sorted(names & set(_LEGACY_TABLES))
    if legacy:
        log.warning(
            "store %s still holds copied history from an older version (tables %s); "
            "nothing reads it. Drop it with: sqlite3 %s %s",
            path,
            ", ".join(legacy),
            shlex.quote(str(path)),
            shlex.quote(" ".join(f"DROP TABLE {name};" for name in legacy)),
        )


# --- serialization -------------------------------------------------------------


def _lesson_row(project: str, lesson: Lesson) -> tuple[str, str, int, bool, str]:
    pain = lesson.pain_point
    return (project, pain.session_id, pain.step, lesson.spark_safe, _lesson_json(lesson))


def _lesson_json(lesson: Lesson) -> str:
    return json.dumps(asdict(lesson))


def _lesson_from_json(body: str) -> Lesson:
    data = json.loads(body)
    return Lesson(
        pain_point=_pain_point_from_dict(data["pain_point"]),
        quote=data["quote"],
        resolution=tuple(data["resolution"]),
        unresolved_because=data["unresolved_because"],
        spark_safe=data["spark_safe"],
        sources=tuple((ref[0], ref[1]) for ref in data["sources"]),
        task_ids=tuple(data["task_ids"]),
        # Rows written before this field existed recorded no such changes.
        changed_alongside=tuple(data.get("changed_alongside", ())),
    )


def _pain_point_from_dict(data: dict[str, Any]) -> PainPoint:
    signature = data["signature"]
    return PainPoint(
        signature=Signature(Signal(signature["signal"]), tuple(signature["key"])),
        session_id=data["session_id"],
        step=data["step"],
        record_refs=tuple((ref[0], ref[1]) for ref in data["record_refs"]),
    )
