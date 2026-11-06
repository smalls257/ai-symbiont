"""A store and settings file written before `spark_safe` became `remote_safe` open intact.

The old spelling is accepted; a lesson with neither flag raises naming it, never reads as shareable.
"""

import json
import sqlite3
from dataclasses import replace

import pytest

from record_builders import PUBLIC, edit, run, session, user
from symbiont.miner.screen import ScreenRules
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.records.schema import Provenance, dump_jsonl, load_jsonl
from symbiont.store.consent import read_consent, record_consent
from symbiont.store.lesson_rows import lesson_from_json
from symbiont.store.local import RemotePrivacyViolationError, Source, Store
from symbiont.store.mining import MiningRules, remine

pytestmark = pytest.mark.periphery

PROJECT = "demo"
READER = "records-jsonl"
PRIVATE = Provenance(dataset="swe-chat", license="see-dataset-card", remote_safe=False)


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def failing(session_id, provenance):
    records = session(
        user("fix it"),
        run("pytest tests/test_cart.py", 1, "cart.py:1\nImportError: x"),
        edit("app/cart.py"),
        run("pytest tests/test_cart.py", 0, "ok"),
    )
    return [
        replace(r, project=PROJECT, session_id=session_id, provenance=provenance) for r in records
    ]


def mined_store(path, *sessions):
    store = Store.open(path)
    sources = []
    for i, records in enumerate(sessions):
        log = path.parent / f"log{i}.jsonl"
        with log.open("w") as fh:
            dump_jsonl(records, fh)
        sources.append(Source(PROJECT, READER, str(log)))
    rules = MiningRules(
        {READER: read_records_jsonl}, frozenset(), screen=ScreenRules(min_sessions=1)
    )
    remine(store, PROJECT, rules, adding=sources)
    return store


def written_before_the_rename(path):
    """Rewrite a store file the way the old code left it: old column, old JSON key."""
    db = sqlite3.connect(path)
    db.execute("ALTER TABLE lessons RENAME COLUMN remote_safe TO spark_safe")
    for rowid, body in db.execute("SELECT rowid, body FROM lessons").fetchall():
        data = json.loads(body)
        data["spark_safe"] = data.pop("remote_safe")
        db.execute("UPDATE lessons SET body = ? WHERE rowid = ?", (json.dumps(data), rowid))
    db.commit()
    db.close()


def test_a_store_written_before_the_rename_opens_with_its_privacy_flags(tmp_path):
    path = tmp_path / "store.db"
    mined_store(path, failing("pub", PUBLIC), failing("priv", PRIVATE))
    written_before_the_rename(path)

    store = Store.open(path)

    flags = {lesson.pain_point.session_id: lesson.remote_safe for lesson in store.lessons(PROJECT)}
    assert flags == {"pub": True, "priv": False}
    with pytest.raises(RemotePrivacyViolationError):
        store.remote_view().lessons(PROJECT)
    columns = {row[1] for row in store._db.execute("PRAGMA table_info(lessons)")}
    assert "remote_safe" in columns and "spark_safe" not in columns


def test_a_lesson_without_any_privacy_flag_raises_naming_it(tmp_path):
    path = tmp_path / "store.db"
    store = mined_store(path, failing("pub", PUBLIC))
    (body,) = [row[0] for row in store._db.execute("SELECT body FROM lessons")]
    data = json.loads(body)
    data.pop("remote_safe")

    with pytest.raises(ValueError, match="pub"):
        lesson_from_json(json.dumps(data))


def test_consent_saved_under_the_old_key_still_counts(tmp_path):
    (tmp_path / "consent.json").write_text(
        '{"own_history_to_spark": "consent"}\n', encoding="utf-8"
    )
    assert read_consent(tmp_path) is OwnHistoryConsent.GIVEN


def test_consent_is_written_under_the_new_key_only(tmp_path):
    record_consent(tmp_path, OwnHistoryConsent.GIVEN)
    saved = json.loads((tmp_path / "consent.json").read_text(encoding="utf-8"))
    assert saved == {"own_history_to_remote": "consent"}


def test_a_record_saved_with_the_old_flag_name_loads_with_its_value():
    line = json.dumps(
        {
            "harness": "h", "project": "p", "session_id": "s", "step": 0, "kind": "user_turn",
            "raw": "x", "files": [],
            "provenance": {"dataset": "d", "license": "l", "spark_safe": False},
        }
    )  # fmt: skip
    (record,) = load_jsonl([line])
    assert record.provenance.remote_safe is False


def test_a_non_boolean_privacy_flag_is_refused_naming_the_lesson(tmp_path):
    store = mined_store(tmp_path / "store.db", failing("pub", PUBLIC))
    (body,) = [row[0] for row in store._db.execute("SELECT body FROM lessons")]
    data = json.loads(body)
    data["remote_safe"] = "false"

    with pytest.raises(ValueError, match="pub"):
        lesson_from_json(json.dumps(data))
