"""Local SQLite store of mined lessons and of where each project's history lives. No raw history.

Kept: sources (project, reader, path pointers to the harness's logs, re-read on every mining) and
lessons (each with its own quote, resolution, privacy flag and ids) until training consumes them.
`remote_view(consent)` raises `RemotePrivacyViolationError` for a lesson a remote model may not
see and returns the rest scrubbed of credentials; hold-out is checked at mining time
(`store.mining`).
"""

import json
import logging
import shlex
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from symbiont.miner.lessons import Lesson, remote_allowed
from symbiont.miner.painpoint import PainPoint
from symbiont.miner.secrets import scrubbed
from symbiont.miner.trained import lesson_id, training_manifest
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.store.catalog import LessonCatalog
from symbiont.store.contexts import LessonContexts
from symbiont.store.curation import Curation
from symbiont.store.group_verdicts import SCHEMA as VERDICTS_SCHEMA
from symbiont.store.group_verdicts import GroupVerdicts
from symbiont.store.held_back import SCHEMA as HELD_BACK_SCHEMA
from symbiont.store.held_back import MiningLedger
from symbiont.store.ignored import SCHEMA as IGNORED_SCHEMA
from symbiont.store.ignored import IgnoredPatterns
from symbiont.store.lesson_rows import lesson_from_json
from symbiont.store.review_state import ReviewState
from symbiont.store.session_summaries import SCHEMA as SUMMARIES_SCHEMA
from symbiont.store.session_summaries import SessionSummaries
from symbiont.store.struggle_rows import SCHEMA as STRUGGLE_SCHEMA
from symbiont.store.struggle_rows import add_missing_started
from symbiont.store.triage import SCHEMA as TRIAGE_SCHEMA
from symbiont.store.triage import (
    GroupTriage,
    add_missing_lesson_id,
    add_missing_name,
    add_missing_until,
)

log = logging.getLogger("symbiont.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    project TEXT NOT NULL, reader TEXT NOT NULL, path TEXT NOT NULL,
    PRIMARY KEY (project, reader, path)
);
CREATE TABLE IF NOT EXISTS lessons (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL,
    remote_safe INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_by_project ON lessons (project, remote_safe);
-- Ids (no text) of lessons a model was trained on, with the export that carried them.
-- The developer's own words about a lesson (store.contexts); not record text.
CREATE TABLE IF NOT EXISTS contexts (
    lesson_id TEXT PRIMARY KEY, project TEXT NOT NULL, text TEXT NOT NULL,
    intentional INTEGER NOT NULL, priority TEXT NOT NULL, applies TEXT NOT NULL
);
-- The developer's answer to "the reviewer thinks this is noise": keep or dismiss.
CREATE TABLE IF NOT EXISTS review_overrides (
    lesson_id TEXT PRIMARY KEY, project TEXT NOT NULL, choice TEXT NOT NULL
);
-- Lessons written in plain words, verdicts on mined pain points, judged correction candidates.
CREATE TABLE IF NOT EXISTS authored (
    id TEXT PRIMARY KEY, project TEXT NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL,
    files TEXT NOT NULL, source_label TEXT NOT NULL, severity TEXT NOT NULL,
    applies TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '', quote_role TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reviews (
    lesson_id TEXT PRIMARY KEY, project TEXT NOT NULL, verdict TEXT NOT NULL,
    rule TEXT NOT NULL, title TEXT NOT NULL, merge_with TEXT, applies TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS decided (
    project TEXT NOT NULL, candidate_id TEXT NOT NULL, PRIMARY KEY (project, candidate_id)
);
CREATE TABLE IF NOT EXISTS trained (
    project TEXT NOT NULL, lesson_id TEXT NOT NULL, export_id TEXT NOT NULL,
    PRIMARY KEY (project, lesson_id)
);
"""
# Tables an older version filled with copied history; read by nothing now.
_LEGACY_TABLES = ("records", "pain_points")


_LATER_AUTHORED_COLUMNS = ("source_url", "quote", "quote_role")


def _add_missing_authored_columns(db: sqlite3.Connection) -> None:
    """Add the columns older stores lack, in place, with an empty default.

    `source_url` came with pull-request lessons; `quote` and `quote_role` with the reviewer's words.
    """
    columns = {row[1] for row in db.execute("PRAGMA table_info(authored)")}
    for name in _LATER_AUTHORED_COLUMNS:
        if name not in columns:
            with db:
                db.execute(f"ALTER TABLE authored ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def _rename_spark_safe_column(db: sqlite3.Connection) -> None:
    """Stores written before the privacy vocabulary went provider-neutral keep `spark_safe`.

    Runs before the schema script so the existing table and its index are renamed in place and
    no flag is lost; the lessons table may not exist yet in a fresh store.
    """
    if not _needs_flag_rename(db):
        return
    db.execute("BEGIN IMMEDIATE")  # a second process opening the same old store waits here
    try:
        if _needs_flag_rename(db):  # re-checked inside the lock: the other process may have won
            db.execute("ALTER TABLE lessons RENAME COLUMN spark_safe TO remote_safe")
            log.info("store: renamed lessons.spark_safe to remote_safe")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _needs_flag_rename(db: sqlite3.Connection) -> bool:
    """True for a lessons table that still carries the pre-rename column."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(lessons)")}
    return "spark_safe" in columns and "remote_safe" not in columns


def _add_missing_review_summary(db: sqlite3.Connection) -> None:
    """Add `reviews.summary` to stores from before the session's model could write one."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(reviews)")}
    if "summary" not in columns:
        with db:
            db.execute("ALTER TABLE reviews ADD COLUMN summary TEXT NOT NULL DEFAULT ''")


class RemotePrivacyViolationError(PermissionError):
    """A read would hand a lesson that is not remote-safe to a remote-bound prompt."""

    def __init__(self, project: str, what: str):
        """Name the project and what is private."""
        super().__init__(
            f"{what} in project {project!r} is not remote-safe; "
            "it must not reach a remote-bound prompt"
        )
        self.project = project


class ForgetMismatchError(RuntimeError):
    """The exported lessons do not match the stored rows one to one; nothing was deleted."""

    def __init__(self, project: str, exported: int, matched: int):
        """Name the project and both counts."""
        super().__init__(
            f"{exported} lessons of {project!r} were exported for training but {matched} "
            "stored rows match them; nothing was forgotten"
        )


@dataclass(frozen=True)
class Source:
    """Where some of a project's history lives: a harness log and the reader that parses it."""

    project: str
    reader: str
    path: str


class Store:
    """Lessons and source pointers; the only persistence the rest of the system sees."""

    def __init__(self, db: sqlite3.Connection):
        """Wrap an open SQLite connection."""
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "Store":
        """Open (creating if needed) the store at `path`."""
        # The threaded service shares one store; it serializes every call under its own lock.
        db = sqlite3.connect(path, check_same_thread=False)
        _rename_spark_safe_column(db)
        db.executescript(_SCHEMA)
        db.executescript(HELD_BACK_SCHEMA)
        db.executescript(STRUGGLE_SCHEMA)
        db.executescript(IGNORED_SCHEMA)
        db.executescript(TRIAGE_SCHEMA)
        add_missing_name(db)
        add_missing_until(db)
        add_missing_lesson_id(db)
        db.executescript(SUMMARIES_SCHEMA)
        db.executescript(VERDICTS_SCHEMA)
        _add_missing_authored_columns(db)
        _add_missing_review_summary(db)
        add_missing_started(db)
        _warn_about_legacy_history(db, path)
        return cls(db)

    def sources(self, project: str) -> list[Source]:
        """Every log registered for `project`, in the order it was added."""
        rows = self._db.execute(
            "SELECT reader, path FROM sources WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        return [Source(project, reader, path) for reader, path in rows]

    def lessons(self, project: str) -> list[Lesson]:
        """The stored lessons of `project`, in the order they were mined, minus ignored patterns.

        This is the one read every note, review and dashboard goes through, so an ignored
        signature is left out everywhere at once; `ignored` lists what was left out.
        """
        rows = self._db.execute(
            "SELECT body FROM lessons WHERE project=? ORDER BY rowid", (project,)
        ).fetchall()
        ignored = self.ignored.signatures(project)
        lessons = [lesson_from_json(body) for (body,) in rows]
        return [item for item in lessons if item.pain_point.signature not in ignored]

    def forget_trained(
        self, project: str, manifest_path: Path, *, exported: Sequence[Lesson]
    ) -> int:
        """Delete the `exported` lessons once a model trained on them; returns the count deleted."""
        rows = self._rows_of(project, {lesson_id(lesson) for lesson in exported})
        if len(rows) != len(exported):
            raise ForgetMismatchError(project, len(exported), len(rows))
        manifest = training_manifest(project, exported)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8") as out:
            json.dump(manifest, out, indent=1)
        with self._db:
            self._db.executemany("DELETE FROM lessons WHERE rowid=?", [(row,) for row in rows])
            deleted = len(rows)
            self._db.executemany(
                "INSERT OR REPLACE INTO trained VALUES (?, ?, ?)",
                [(project, lesson_id(lesson), manifest["export_id"]) for lesson in exported],
            )
        log.info("deleted %d trained lessons of %s; manifest %s", deleted, project, manifest_path)
        return deleted

    def _rows_of(self, project: str, ids: set[str]) -> list[int]:
        """Row ids of the project's stored lessons whose ids are in `ids`."""
        rows = self._db.execute("SELECT rowid, body FROM lessons WHERE project=?", (project,))
        return [row for row, body in rows if lesson_id(lesson_from_json(body)) in ids]

    def trained_lesson_ids(self, project: str) -> frozenset[str]:
        """Ids of `project`'s lessons a model has already been trained on."""
        rows = self._db.execute("SELECT lesson_id FROM trained WHERE project=?", (project,))
        return frozenset(row[0] for row in rows)

    @property
    def mined(self) -> MiningLedger:
        """Saving a mining run, and reading what it held back, in the same database."""
        return MiningLedger(self._db)

    @property
    def ignored(self) -> IgnoredPatterns:
        """Patterns the developer set aside, in the same database."""
        return IgnoredPatterns(self._db)

    @property
    def review(self) -> ReviewState:
        """The developer's triage of failure groups and their session model's summaries."""
        return ReviewState(
            GroupTriage(self._db), SessionSummaries(self._db), GroupVerdicts(self._db)
        )

    @property
    def contexts(self) -> LessonContexts:
        """The developer's own words about lessons, in the same database."""
        return LessonContexts(self._db)

    @property
    def curation(self) -> Curation:
        """Written lessons, verdicts and judged correction candidates, in the same database."""
        return Curation(self._db)

    @property
    def catalog(self) -> LessonCatalog:
        """Questions across projects: which projects exist, which project owns a lesson id."""
        return LessonCatalog(self._db)

    def remote_view(self, consent: OwnHistoryConsent = OwnHistoryConsent.WITHHELD) -> "RemoteView":
        """A read-only view that raises rather than return anything a remote model may not see.

        `consent` is the user's own-history setting (`store.consent`); withheld unless given.
        """
        return RemoteView(self, consent)


class RemoteView:
    """Read-only; every read raises rather than return a lesson a remote model may not see."""

    def __init__(self, store: Store, consent: OwnHistoryConsent):
        """Wrap the store with the user's consent setting."""
        self._store = store
        self._consent = consent

    def lessons(self, project: str) -> list[Lesson]:
        """Scrubbed lessons of `project`, or RemotePrivacyViolationError if any is not allowed.

        Without consent any private lesson raises; with it, only third-party ones do.
        Credentials are scrubbed from every lesson returned.
        """
        lessons = self._store.lessons(project)
        if any(not remote_allowed(lesson, self._consent) for lesson in lessons):
            raise RemotePrivacyViolationError(project, "a lesson")
        return [scrubbed(lesson) for lesson in lessons]

    def pain_points(self, project: str) -> list[PainPoint]:
        """Pain points of `project`, or RemotePrivacyViolationError if any lesson is private."""
        return [lesson.pain_point for lesson in self.lessons(project)]


def _warn_about_legacy_history(db: sqlite3.Connection, path: Path) -> None:
    """Warn when the database still holds copied history from an older version."""
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
