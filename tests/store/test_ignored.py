"""Ignoring a pattern hides every occurrence of it, now and after a re-mine, until restored.

Failure guarded against: an "Ignore" that hides one lesson and lets the same trouble come back
on the next mine, or one that makes the pattern vanish with no way to see or undo it.
"""

from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont.miner.screen import HoldReason, ScreenRules
from symbiont.miner.trained import lesson_id
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine

pytestmark = pytest.mark.periphery

PROJECT = "demo"
READER = "records-jsonl"
TEST = "pytest tests/test_parser.py"
BROKEN = "app/parser.py:1\nImportError: cannot import name 'parse'"


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def fixed_in(session_id):
    steps = session(run(TEST, 1, BROKEN), edit("app/parser.py"), run(TEST, 0, "1 passed"))
    return [replace(r, session_id=session_id, project=PROJECT) for r in steps]


def mine(tmp_path, store):
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl(fixed_in("a") + fixed_in("b"), fh)
    rules = MiningRules(
        {READER: read_records_jsonl}, frozenset(), screen=ScreenRules(min_sessions=1)
    )
    adding = [Source(PROJECT, READER, str(path))] if not store.sources(PROJECT) else []
    return remine(store, PROJECT, rules, adding=adding)


@pytest.fixture
def mined(tmp_path):
    store = Store.open(tmp_path / "store.db")
    return store, mine(tmp_path, store)


def test_an_ignored_signature_is_left_out_of_lessons_and_pain_points(mined):
    store, lessons = mined
    signature = lessons[0].pain_point.signature

    store.ignored.add(PROJECT, [signature], "The parser import fails")

    assert store.lessons(PROJECT) == []
    assert store.remote_view().pain_points(PROJECT) == []
    assert store.ignored.listed(PROJECT) == [((signature,), "The parser import fails")]


def test_ignoring_one_occurrence_ignores_every_occurrence_of_its_pattern(mined):
    store, lessons = mined
    assert len({lesson.pain_point.session_id for lesson in lessons}) == 2

    store.ignored.add(PROJECT, [lessons[0].pain_point.signature], "label")

    assert [lesson_id(item) for item in store.lessons(PROJECT)] == []
    assert store.lessons("other") == []


def test_an_ignored_pattern_stays_ignored_after_a_remine(tmp_path, mined):
    store, lessons = mined
    store.ignored.add(PROJECT, [lessons[0].pain_point.signature], "label")

    mine(tmp_path, store)

    assert store.lessons(PROJECT) == []
    assert store.mined.counts(PROJECT)[HoldReason.IGNORED] == 1


def test_ignore_then_remine_then_restore_brings_the_lessons_back(tmp_path, mined):
    """Failure guarded against: a re-mine drops ignored lessons, so Restore restores nothing."""
    store, lessons = mined
    signature = lessons[0].pain_point.signature
    store.ignored.add(PROJECT, [signature], "label")
    mine(tmp_path, store)

    assert store.ignored.remove(PROJECT, signature) is True

    assert sorted(lesson_id(item) for item in store.lessons(PROJECT)) == sorted(
        lesson_id(item) for item in lessons
    )


def test_restoring_brings_the_lessons_back_without_a_remine(mined):
    store, lessons = mined
    signature = lessons[0].pain_point.signature
    store.ignored.add(PROJECT, [signature], "label")

    assert store.ignored.remove(PROJECT, signature) is True

    assert [lesson_id(item) for item in store.lessons(PROJECT)] == [
        lesson_id(item) for item in lessons
    ]
    assert store.ignored.remove(PROJECT, signature) is False
    assert store.ignored.listed(PROJECT) == []


def test_ignored_patterns_survive_reopening_the_store(tmp_path, mined):
    store, lessons = mined
    store.ignored.add(PROJECT, [lessons[0].pain_point.signature], "label")

    reopened = Store.open(tmp_path / "store.db")

    assert reopened.ignored.signatures(PROJECT) == {lessons[0].pain_point.signature}


def test_restoring_any_signature_of_a_row_brings_back_the_whole_row(mined):
    store, lessons = mined
    first = lessons[0].pain_point.signature
    other = replace(first, key=("pytest", "tests/test_other.py", "KeyError"))
    store.ignored.add(PROJECT, [first, other], "one row")

    assert store.ignored.listed(PROJECT) == [((first, other), "one row")]
    assert store.ignored.remove(PROJECT, other) is True

    assert store.ignored.signatures(PROJECT) == frozenset()
