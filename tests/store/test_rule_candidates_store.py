"""Mining keeps the turns that may state a rule, replaces them on a re-mine, and keeps no secret."""

from dataclasses import replace

import pytest

from record_builders import session, user
from symbiont.miner.rule_groups import group_by_terms
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine

pytestmark = pytest.mark.periphery

PROJECT = "demo"
READER = "records-jsonl"
SECRET = "abcd1234" + "efgh5678"  # built at runtime so no secret scanner reads a literal


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def mine(tmp_path, store, *turns, name="log.jsonl"):
    records = [replace(r, session_id=name) for r in session(*(user(t) for t in turns))]
    path = tmp_path / name
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    rules = MiningRules({READER: read_records_jsonl}, frozenset())
    remine(store, PROJECT, rules, adding=[Source(PROJECT, READER, str(path))])


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.db")


def test_candidates_are_stored_scrubbed_and_group_on_read(tmp_path, store):
    mine(tmp_path, store, f"always use pnpm, never npm token={SECRET}", "thanks")
    (stored,) = store.mined.rule_candidates(PROJECT)
    assert SECRET not in stored.text
    assert {"pnpm", "npm"} <= stored.terms
    assert len(group_by_terms(store.mined.rule_candidates(PROJECT))) == 1


def test_a_remine_replaces_the_candidates(tmp_path, store):
    mine(tmp_path, store, "always use pnpm")
    mine(tmp_path, store, "never commit to main", name="two.jsonl")
    texts = {c.text for c in store.mined.rule_candidates(PROJECT)}
    assert texts == {"always use pnpm", "never commit to main"}
    mine(tmp_path, store, "never commit to main", name="two.jsonl")
    assert len(store.mined.rule_candidates(PROJECT)) == 2
