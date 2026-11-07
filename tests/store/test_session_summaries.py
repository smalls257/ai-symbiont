"""Summaries and topics are the developer's session model's work: a re-mine must keep them.

Failure guarded against: Silent Fallback (a re-mine that quietly empties the summaries makes the
model redo, and the developer pay for, every batch).
"""

import pytest

from record_builders import run, session, user
from store_builders import save_lessons
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.topics import CorrectionGroup, Group, TopicMap
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
PROJECT = "demo"


def summary(ident, goal="Fix refunds"):
    return SessionSummary(ident, goal, SummaryOutcome.DONE, "slow tests", False)


def topic_map():
    return TopicMap(
        (Group("Refunds and billing", "money", ("a", "b")),),
        (Group("Slow tests", "waiting", ("a",)),),
        (CorrectionGroup("Back to main", "git", (("a", 3),)),),
    )


def test_summaries_are_kept_and_the_summarized_ids_are_listed(tmp_path):
    store = Store.open(tmp_path / "s.db")

    store.summaries.save(PROJECT, [summary("a"), summary("b")])
    store.summaries.save(PROJECT, [summary("a", "Fix refund rounding")])

    assert store.summaries.summarized(PROJECT) == frozenset({"a", "b"})
    assert [item.goal for item in store.summaries.all(PROJECT)] == [
        "Fix refund rounding",
        "Fix refunds",
    ]
    assert store.summaries.all("other") == []


def test_a_topic_map_round_trips_and_a_new_map_replaces_the_old_one(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.summaries.save_topics(PROJECT, topic_map())

    assert store.summaries.topics(PROJECT) == topic_map()

    store.summaries.save_topics(PROJECT, TopicMap((), (), ()))
    assert store.summaries.topics(PROJECT) == TopicMap((), (), ())


def test_a_remine_keeps_summaries_and_topics(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.summaries.save(PROJECT, [summary("a")])
    store.summaries.save_topics(PROJECT, topic_map())

    save_lessons(store, PROJECT, [], [], held_out_tasks=frozenset())

    assert store.summaries.summarized(PROJECT) == frozenset({"a"})
    assert store.summaries.topics(PROJECT) == topic_map()


def test_the_summary_goal_becomes_the_session_title_on_the_facts(tmp_path):
    from dataclasses import replace

    from symbiont.miner.struggle import facts_of
    from symbiont.miner.themes import Codebase
    from symbiont.store.held_back import MiningOutcome

    store = Store.open(tmp_path / "s.db")
    steps = [
        replace(r, session_id="a")
        for r in session(user("make the parser faster please"), run("ls"))
    ]
    facts = facts_of([steps], [], Codebase(frozenset({"demo"})), frozenset())
    store.mined.save(PROJECT, [], MiningOutcome([], facts=facts), held_out_tasks=frozenset())
    assert store.mined.session_facts(PROJECT)[0].title == "make the parser faster please"

    store.summaries.save(PROJECT, [summary("a", "Speed up the parser")])

    assert store.mined.session_facts(PROJECT)[0].title == "Speed up the parser"


def test_a_store_made_before_summaries_existed_still_reads_its_facts(tmp_path):
    import sqlite3
    from dataclasses import replace

    from symbiont.miner.struggle import facts_of
    from symbiont.miner.themes import Codebase
    from symbiont.store.held_back import MiningOutcome

    path = tmp_path / "old.db"
    steps = [
        replace(r, session_id="a")
        for r in session(user("make the parser faster please"), run("ls"))
    ]
    facts = facts_of([steps], [], Codebase(frozenset({"demo"})), frozenset())
    Store.open(path).mined.save(
        PROJECT, [], MiningOutcome([], facts=facts), held_out_tasks=frozenset()
    )
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE session_summaries")
        db.execute("DROP TABLE topics")

    reopened = Store.open(path)

    assert reopened.mined.session_facts(PROJECT)[0].title == "make the parser faster please"
    assert reopened.mined.session_strips(PROJECT) == []
