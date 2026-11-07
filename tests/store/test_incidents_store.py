"""Incidents are stored with the lessons and replaced by a re-mine, leaving other state alone."""

from dataclasses import replace

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.incident_types import Outcome
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
        user("the parser fails"), run(TEST, 1, BROKEN), edit("app/parser.py"), run(TEST, 0, "ok")
    )
    return [replace(r, session_id=session_id) for r in steps]


def never_fixed(session_id):
    steps = session(user("go"), run("make lint", 2, "lint: 3 problems"))
    return [replace(r, session_id=session_id) for r in steps]


def mine(tmp_path, store, records, name="log.jsonl"):
    path = tmp_path / name
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    rules = MiningRules({READER: read_records_jsonl}, frozenset())
    remine(store, PROJECT, rules, adding=[Source(PROJECT, READER, str(path))])


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_incidents_round_trip_for_kept_and_unscreened_failures(tmp_path, store):
    mine(tmp_path, store, fixed_in("s1") + never_fixed("s2"))
    saved = store.mined.incidents(PROJECT)
    assert {c.session_id for c in saved} == {"s1", "s2"}
    by_session = {c.session_id: c for c in saved}
    assert by_session["s1"].outcome is Outcome.FIXED_IN_CODE
    assert by_session["s1"].fingerprint.startswith("failure:pytest:")
    assert by_session["s1"].example == TEST
    assert by_session["s2"].outcome is Outcome.NEVER_FIXED


def test_a_remine_replaces_incidents_and_keeps_the_rest(tmp_path, store):
    mine(tmp_path, store, fixed_in("s1"))
    store.review.summaries.save_topics(PROJECT, store.review.summaries.topics(PROJECT))
    first = store.mined.incidents(PROJECT)
    mine(tmp_path, store, fixed_in("s1"))
    assert store.mined.incidents(PROJECT) == first
    assert len(store.sources(PROJECT)) == 1
