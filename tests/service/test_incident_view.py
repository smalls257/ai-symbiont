"""The `incidents` data: Inbox groups, cards by topic, noise with reasons, null for no date."""

from dataclasses import replace

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.miner.topics import Group, TopicMap
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.incident_view import IncidentContext, incident_groups, incidents_snapshot
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine


def card(session, step=1, topic="", noise=None, program="pytest", example="pytest tests"):
    return Incident(
        session_id=session, step=step, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed.", outcome=Outcome.FIXED_IN_CODE,
        noise=noise, topic=topic, files=("app.py",), situation=("running", program, "tests"),
        fingerprint=f"failure:{program}:boom", example=example,
    )  # fmt: skip


pytestmark = pytest.mark.periphery
DAYS = {"a": "2026-10-05", "b": "2026-10-06", "c": "2026-10-20", "u": None}


def test_cards_are_grouped_by_topic_newest_first():
    cards = [card("a", topic="Parser"), card("c", topic="Parser"), card("b", topic="Build")]
    context = IncidentContext(topic_descriptions={"Parser": "Fixing the parser"})
    shown = incident_groups(cards, DAYS, context)["topics"]
    assert [t["topic"] for t in shown] == ["Parser", "Build"]
    parser = next(t for t in shown if t["topic"] == "Parser")
    assert [c["date"] for c in parser["worth"]] == ["2026-10-20", "2026-10-05"]
    assert parser["description"] == "Fixing the parser"
    assert parser["sessions"] == 2


def test_all_noise_project_still_lists_the_noise_with_reasons():
    noisy = [
        card("a", topic="Parser", noise=NoiseReason.PLAIN_RETRY),
        card("b", topic="Parser", noise=NoiseReason.PLAIN_RETRY),
        card("c", topic="Parser", noise=NoiseReason.LOOK_AROUND),
    ]
    shown = incident_groups(noisy, DAYS)
    topic = shown["topics"][0]
    assert topic["worth"] == []
    assert topic["noise"] == {"plain_retry": 2, "look_around": 1}
    assert shown["noise"]["total"] == 3
    assert shown["noise"]["byReason"][0]["count"] == 2
    assert shown["groups"][0]["noise"] == "plain_retry"


def test_an_undated_card_says_null():
    shown = incident_groups([card("u")], DAYS)
    group = shown["groups"][0]
    assert shown["noTopic"][0]["date"] is None
    assert (group["first"], group["last"], group["weekly"], group["undated"]) == (None, None, [], 1)


def test_a_group_has_a_real_title_counts_weeks_and_trigger():
    cards = [card("a", example="pytest -x tests/a"), card("b"), card("c")]
    group = incident_groups(cards, DAYS, IncidentContext(titles={"c": "Fix parser"}))["groups"][0]
    assert group["title"] == "pytest tests"
    assert (group["times"], group["sessions"], group["kind"]) == (3, 3, "failure")
    assert group["weekly"] == [["2026-W41", 2], ["2026-W43", 1]]
    assert (group["first"], group["last"]) == ("2026-10-05", "2026-10-20")
    assert group["trigger"]["program"] == "pytest"
    assert group["key"] == "failure:pytest:boom"
    assert group["cards"][0]["session"] == "Fix parser"
    assert group["verdict"] == "fixed in the code"


def test_a_group_without_a_shared_situation_has_no_trigger():
    mixed = [card("a"), card("b", program="npm"), card("c", program="make")]
    shown = incident_groups(mixed, DAYS)
    assert all(g["trigger"] is not None for g in shown["groups"])
    cards = [card("a"), card("b")]
    cards[1] = Incident(**{**cards[1].__dict__, "situation": ("", "", "")})
    assert incident_groups(cards, DAYS)["groups"][0]["trigger"] is None


def test_the_snapshot_of_a_mined_store_reads_topics_and_titles_from_the_review_state(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_one_failure(tmp_path, store)
    store.review.summaries.save_topics(
        "demo", TopicMap((Group("Parser work", "Fixing it", ("s1",)),), (), ())
    )
    shown = incidents_snapshot(store, "demo")
    assert shown["topics"][0]["topic"] == "Parser work"
    assert shown["topics"][0]["description"] == "Fixing it"
    assert shown["groups"][0]["key"].startswith("failure:pytest:")


def mine_one_failure(tmp_path, store):
    steps = session(
        user("fix"), run("pytest t.py", 1, "a.py:1\nImportError: x"), edit("a.py"),
        run("pytest t.py", 0, "ok"),
    )  # fmt: skip
    path = tmp_path / "log.jsonl"
    with path.open("w") as fh:
        dump_jsonl([replace(r, session_id="s1") for r in steps], fh)
    rules = MiningRules({"jsonl": lambda p, project: iter(list(load_jsonl(p.open())))}, frozenset())
    remine(store, "demo", rules, adding=[Source("demo", "jsonl", str(path))])


def fixed_card(session, outcome):
    return Incident(**{**card(session).__dict__, "outcome": outcome})


def recurring_of(cards):
    return incident_groups(cards, DAYS)["groups"][0]["recurring"]


def test_a_group_seen_once_and_never_fixed_is_not_recurring():
    assert recurring_of([fixed_card("a", Outcome.NEVER_FIXED)]) is False


def test_a_group_in_two_sessions_is_recurring():
    cards = [fixed_card("a", Outcome.NEVER_FIXED), fixed_card("b", Outcome.NEVER_FIXED)]
    assert recurring_of(cards) is True


def test_a_single_session_group_with_a_code_or_setup_fix_is_recurring():
    assert recurring_of([fixed_card("a", Outcome.FIXED_IN_CODE)]) is True
    assert recurring_of([fixed_card("a", Outcome.ENVIRONMENT_FIXED)]) is True
    assert recurring_of([fixed_card("a", Outcome.PASSED_ON_RETRY)]) is False


def test_a_session_dropped_from_the_topic_map_loses_its_topic(tmp_path):
    store = Store.open(tmp_path / "s.db")
    summaries = store.review.summaries
    summaries.save_topics("demo", TopicMap((Group("Parser work", "x", ("s1",)),), (), ()))
    mine_one_failure(tmp_path, store)
    assert incidents_snapshot(store, "demo")["topics"]
    summaries.save_topics("demo", TopicMap((), (), ()))
    assert incidents_snapshot(store, "demo")["topics"] == []
