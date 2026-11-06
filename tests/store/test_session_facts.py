"""Mining keeps one row of facts per session, beside the lessons, and replaces them on a re-mine."""

from dataclasses import replace

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.patterns import StrugglePattern
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
    steps = session(
        user("the parser fails"),
        run(TEST, 1, BROKEN),
        edit("app/parser.py"),
        run(TEST, 0, "1 passed"),
        run("pytest tests/nope.py", 4, "usage"),
    )
    return [replace(r, session_id=session_id) for r in steps]


def mine(tmp_path, store, records):
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    rules = MiningRules({READER: read_records_jsonl}, frozenset())
    remine(store, PROJECT, rules, adding=[Source(PROJECT, READER, str(path))])


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_mining_saves_one_facts_row_per_session(tmp_path, store):
    mine(tmp_path, store, [*fixed_in("s1"), *fixed_in("s2"), *fixed_in("s3")])

    facts = store.mined.session_facts(PROJECT)

    assert [f.session_id for f in facts] == ["s1", "s2", "s3"]
    first = facts[0]
    assert first.task_label == "the parser fails" and first.turns_lost > 0
    assert StrugglePattern.TESTS_NOT_FOUND in first.patterns
    assert first.outcomes == {"code_fix": 1, "never": 1}


def test_a_re_mine_replaces_the_facts_and_the_strips(tmp_path, store):
    mine(tmp_path, store, [*fixed_in("s1"), *fixed_in("s2")])
    mine(tmp_path, store, fixed_in("only"))

    assert [f.session_id for f in store.mined.session_facts(PROJECT)] == ["only"]
    assert {s.session_id for s in store.mined.session_strips(PROJECT)} == {"only"}


def test_a_project_never_mined_has_no_facts(store):
    assert store.mined.session_facts("other") == []
    assert store.mined.session_strips("other") == []


def test_a_strip_keeps_where_its_window_starts_and_one_stored_before_windows_still_reads(
    tmp_path, store
):
    import json

    storm = [run(f"pytest t{n}", 1, BROKEN) for n in range(30)]
    quiet = [run("pytest ok", 0)] * 800
    mine(tmp_path, store, [replace(r, session_id="long") for r in session(*quiet, *storm)])

    (strip,) = store.mined.session_strips(PROJECT)
    assert strip.offset > 0 and len(strip.steps) == 600 and strip.total_steps == 830

    old = json.dumps([[3, "failed", "pytest t"]])
    store._db.execute("UPDATE session_strips SET steps=?", (old,))
    (before,) = store.mined.session_strips(PROJECT)
    assert before.offset == 0 and before.steps[0].step == 3
