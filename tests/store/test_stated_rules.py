"""Confirmed rules are the model's paid work: a re-mine must not empty them.

Failure guarded against: Silent Fallback (a re-mine that quietly drops rules bills again).
"""

import sqlite3
from datetime import date

import pytest

from symbiont.miner.stated_rule import RuleScope, StatedRule
from symbiont.store.held_back import REPLACED_TABLES
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
DAY = date(2026, 11, 7)


def test_rules_and_drops_round_trip_per_project_and_a_rewrite_replaces(tmp_path):
    store = Store.open(tmp_path / "s.db")
    first = StatedRule("Use uv.", RuleScope.REPO, "", (("a", 1), ("b", 2)))
    again = StatedRule("Always use uv.", RuleScope.AREA, "scripts/", (("a", 1),))

    store.review.rules.save("demo", [first], [("c", 3)], DAY)
    store.review.rules.save("demo", [again], [], DAY)

    assert store.review.rules.rules("demo") == [again]
    assert store.review.rules.covered("demo") == {("a", 1), ("c", 3)}
    assert store.review.rules.rules("other") == [] and store.review.rules.covered("other") == set()


def test_the_tables_are_developer_owned_and_survive_a_remine():
    assert not {"stated_rules", "dropped_rule_candidates"} & set(REPLACED_TABLES)


def test_an_old_store_without_the_tables_opens_and_reads_empty(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sources (project TEXT, reader TEXT, path TEXT)")
    db.commit()
    db.close()

    store = Store.open(path)

    assert store.review.rules.rules("demo") == []
