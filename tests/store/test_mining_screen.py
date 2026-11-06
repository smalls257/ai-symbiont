"""Mining screens lessons: only groups with a shown fix are stored; the rest are counted."""

from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont.miner.screen import HoldReason, ScreenRules
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
    return [replace(r, session_id=session_id) for r in steps]


def struggled_in(session_id):
    steps = session(run("make lint", 2, "make: *** [lint] Error 2"), run("make lint -j", 0, ""))
    return [replace(r, session_id=session_id) for r in steps]


def mine(tmp_path, store, records, min_sessions):
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    rules = MiningRules(
        {READER: read_records_jsonl},
        frozenset(),
        screen=ScreenRules(min_sessions=min_sessions),
    )
    return remine(store, PROJECT, rules, adding=[Source(PROJECT, READER, str(path))])


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_remine_saves_only_kept_lessons_and_records_the_held_back_counts(tmp_path, store):
    records = [*fixed_in("s1"), *fixed_in("s2"), *struggled_in("s3"), *struggled_in("s4")]
    kept = mine(tmp_path, store, records, min_sessions=2)
    assert len(kept) == 2 and store.lessons(PROJECT) == kept
    assert store.mined.counts(PROJECT) == {HoldReason.NO_FIX_SHOWN: 1}
    (group,) = store.mined.struggle(PROJECT)
    assert (group.signature.key[0], group.sessions, group.occurrences) == ("make", 2, 2)


def test_raising_min_sessions_then_remining_holds_more_back(tmp_path, store):
    records = [*fixed_in("s1"), *fixed_in("s2")]
    assert len(mine(tmp_path, store, records, min_sessions=2)) == 2
    assert store.mined.counts(PROJECT) == {}
    assert mine(tmp_path, store, records, min_sessions=3) == []
    assert store.mined.counts(PROJECT) == {HoldReason.TOO_FEW_SESSIONS: 1}
    assert len(mine(tmp_path, store, records, min_sessions=1)) == 2
