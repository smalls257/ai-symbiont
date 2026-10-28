"""The local store keeps lessons and source pointers, never raw history; its guards raise.

Synthetic logs are written as records JSONL and read back through a test reader
standing in for a harness reader. Hand-written records only.
"""

import json
import logging
import sqlite3
from dataclasses import replace

import pytest

from record_builders import PUBLIC, edit, replace_text, run, session, user
from symbiont.eval.training_manifest import check_manifest_against_hold_out
from symbiont.miner.painpoint import Signal
from symbiont.miner.trained import export_id_of
from symbiont.records.holdout import HoldOutViolationError, UnrecognisedTaskIdError
from symbiont.records.schema import Provenance, dump_jsonl, load_jsonl
from symbiont.store.local import Source, SparkPrivacyViolationError, Store
from symbiont.store.mining import MiningRules, UnknownReaderError, remine
from symbiont.store.training import lessons_for_memory_model, lessons_for_personal_model

pytestmark = pytest.mark.periphery

PROJECT = "tobymao/sqlglot"
SWE_CHAT = Provenance(dataset="SWE-chat", license="ODC-BY", spark_safe=False)
READER = "records-jsonl"
SECRET_OUTPUT = "AssertionError: secret-looking output that must not be copied"


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def rules(held_out=()):
    return MiningRules({READER: read_records_jsonl}, frozenset(held_out))


def failing_session(session_id="s1", task_id="tobymao__sqlglot-1000", provenance=PUBLIC):
    records = session(
        user("fix it"),
        run("pytest tests/test_parser.py", 1, SECRET_OUTPUT),
        edit("sqlglot/parser.py"),
    )
    return [
        replace(r, session_id=session_id, task_id=task_id, provenance=provenance) for r in records
    ]


def log_of(tmp_path, name, records):
    path = tmp_path / f"{name}.jsonl"
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    return Source(PROJECT, READER, str(path))


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.sqlite")


def test_mining_keeps_lessons_and_pointers_but_no_raw_history(tmp_path, store):
    source = log_of(tmp_path, "a", failing_session())
    (lesson,) = remine(store, PROJECT, rules(), adding=[source])
    assert store.sources(PROJECT) == [source]
    assert Store.open(tmp_path / "store.sqlite").lessons(PROJECT) == [lesson]
    db = sqlite3.connect(tmp_path / "store.sqlite")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"sources", "lessons", "trained"}
    (body,) = db.execute("SELECT body FROM lessons").fetchone()
    assert "fix it" not in body, "only the cited record's bounded quote is kept"


def test_mining_re_reads_the_logs_every_time(tmp_path, store):
    source = log_of(tmp_path, "a", failing_session())
    remine(store, PROJECT, rules(), adding=[source])
    log_of(tmp_path, "a", failing_session() + [replace(failing_session()[1], step=3)])
    assert len(remine(store, PROJECT, rules())) == 2


def test_a_missing_or_unknown_source_raises_naming_it(tmp_path, store):
    source = log_of(tmp_path, "a", failing_session())
    remine(store, PROJECT, rules(), adding=[source])
    (tmp_path / "a.jsonl").unlink()
    with pytest.raises(OSError, match="a.jsonl"):
        remine(store, PROJECT, rules())
    with pytest.raises(UnknownReaderError, match="nope"):
        remine(store, "other", rules(), adding=[Source("other", "nope", "x")])


def test_hold_out_is_checked_at_mining_time_and_nothing_is_stored(tmp_path, store):
    source = log_of(tmp_path, "held", failing_session(task_id="tobymao__sqlglot-2000"))
    with pytest.raises(HoldOutViolationError, match="sqlglot-2000"):
        remine(store, PROJECT, rules({"tobymao/sqlglot#2000"}), adding=[source])
    assert store.lessons(PROJECT) == [] and store.sources(PROJECT) == []


def test_an_unrecognised_task_id_is_refused_when_something_is_held_out(tmp_path, store):
    source = log_of(tmp_path, "a", failing_session(task_id="sqlglot-4001"))
    with pytest.raises(UnrecognisedTaskIdError):
        remine(store, PROJECT, rules({"tobymao/sqlglot#1"}), adding=[source])


def test_spark_view_raises_on_a_private_lesson_and_never_filters(tmp_path, store):
    public = log_of(tmp_path, "a", failing_session())
    remine(store, PROJECT, rules(), adding=[public])
    assert len(store.spark_view().lessons(PROJECT)) == 1
    private = log_of(tmp_path, "p", failing_session("chat-1", None, SWE_CHAT))
    remine(store, PROJECT, rules(), adding=[private])
    with pytest.raises(SparkPrivacyViolationError):
        store.spark_view().lessons(PROJECT)
    with pytest.raises(SparkPrivacyViolationError):
        store.spark_view().pain_points(PROJECT)
    assert not hasattr(store.spark_view(), "save_mining")


def test_the_two_training_exports_differ_only_in_the_privacy_guard(tmp_path, store):
    private = log_of(tmp_path, "p", failing_session("chat-1", None, SWE_CHAT))
    remine(store, PROJECT, rules(), adding=[private])
    assert len(lessons_for_personal_model(store, PROJECT)) == 1
    with pytest.raises(SparkPrivacyViolationError):
        lessons_for_memory_model(store, PROJECT)


def test_forget_trained_leaves_a_manifest_of_ids_and_counts_only(tmp_path, store):
    source = log_of(tmp_path, "a", failing_session())
    remine(store, PROJECT, rules(), adding=[source])
    manifest = tmp_path / "manifests" / "run-1.json"
    exported = lessons_for_memory_model(store, PROJECT)
    assert store.forget_trained(PROJECT, manifest, exported=exported) == 1
    assert store.lessons(PROJECT) == []
    text = manifest.read_text()
    assert "AssertionError" not in text and "pytest" not in text
    written = json.loads(text)
    assert written["counts"] == {"lessons": 1, "source_sessions": 1}
    assert written["export_id"] == export_id_of(exported)
    assert written["lessons"][0]["task_ids"] == ["tobymao__sqlglot-1000"]
    assert check_manifest_against_hold_out(manifest, frozenset({"tobymao/sqlglot#9"})) == 1
    with pytest.raises(HoldOutViolationError):
        check_manifest_against_hold_out(manifest, frozenset({"tobymao/sqlglot#1000"}))


def test_forget_trained_never_overwrites_a_manifest_and_then_deletes_nothing(tmp_path, store):
    remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "a", failing_session())])
    manifest = tmp_path / "run-1.json"
    manifest.write_text("{}")
    with pytest.raises(FileExistsError):
        store.forget_trained(PROJECT, manifest, exported=store.lessons(PROJECT))
    assert len(store.lessons(PROJECT)) == 1


def test_opening_a_store_with_copied_history_warns(tmp_path, caplog):
    path = tmp_path / "old.sqlite"
    sqlite3.connect(path).execute("CREATE TABLE records (body TEXT)")
    with caplog.at_level(logging.WARNING, logger="symbiont.store"):
        Store.open(path)
    assert "copied history" in caplog.text and "DROP TABLE records;" in caplog.text


def _edit_session(session_id, old, new, ts):
    return [
        replace(r, session_id=session_id, ts=ts, task_id=None)
        for r in session(replace_text("sqlglot/parser.py", old, new))
    ]


def _rework(store):
    return [p for p in store.pain_points(PROJECT) if p.signature.signal == Signal.REWORKED_EDIT]


def test_rework_is_found_across_logs_of_timed_sessions_in_time_order(tmp_path, store):
    earlier = _edit_session("b-monday", "x = 1", "x = compute_offset(node)", "2026-10-26T09:00:00Z")
    later = _edit_session("a-tuesday", "x = compute_offset(node)", "x = 2", "2026-10-27T09:00:00Z")
    logs = [log_of(tmp_path, "tue", later), log_of(tmp_path, "mon", earlier)]
    remine(store, PROJECT, rules(), adding=logs)
    (pain,) = _rework(store)
    assert (pain.session_id, pain.record_refs) == ("a-tuesday", (("b-monday", 0), ("a-tuesday", 0)))


def test_untimed_sessions_are_mined_alone(tmp_path, store):
    first = _edit_session("t1", "x = 1", "x = compute_offset(node)", None)
    second = _edit_session("t2", "x = compute_offset(node)", "x = 2", None)
    remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "both", first + second)])
    assert _rework(store) == []


def test_forget_trained_deletes_only_the_exported_lessons(tmp_path, store):
    remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "a", failing_session())])
    (exported,) = store.lessons(PROJECT)
    remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "b", failing_session("s2"))])
    assert store.forget_trained(PROJECT, tmp_path / "m.json", exported=[exported]) == 1
    assert [p.session_id for p in store.pain_points(PROJECT)] == ["s2"]


def test_the_memory_model_is_not_offered_lessons_it_was_trained_on(tmp_path, store):
    remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "a", failing_session())])
    store.forget_trained(PROJECT, tmp_path / "m.json", exported=store.lessons(PROJECT))
    remine(store, PROJECT, rules())  # re-mining recreates the trained lesson
    assert len(store.lessons(PROJECT)) == 1
    assert lessons_for_memory_model(store, PROJECT) == []
    assert len(lessons_for_personal_model(store, PROJECT)) == 1


def test_the_write_path_itself_refuses_a_held_out_lesson(tmp_path, store):
    (lesson,) = remine(store, PROJECT, rules(), adding=[log_of(tmp_path, "a", failing_session())])
    with pytest.raises(HoldOutViolationError):
        store.save_mining(PROJECT, [], [lesson], held_out_tasks=frozenset({"tobymao/sqlglot#1000"}))
    assert store.lessons(PROJECT) == [lesson]
