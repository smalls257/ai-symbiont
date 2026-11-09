"""The `topicView` data: outcomes add up, quiet months are 0, a friction counts a session once."""

from datetime import date

from quiet_store import mine_a_session_without_failures
from symbiont.miner.incident_types import Incident, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.struggle import SessionFacts
from symbiont.miner.topics import Group, TopicMap
from symbiont.service.topic_view import MIN_SUMMARIES, sessions_by_date, topic_snapshot, topic_view
from symbiont.store.local import Store

DONE, PARTLY, STUCK = SummaryOutcome.DONE, SummaryOutcome.PARTLY, SummaryOutcome.STUCK


def summary(sid, outcome=DONE, friction="", noise=False):
    return SessionSummary(sid, f"goal {sid}", outcome, friction, noise)


def many(count, prefix="s"):
    return [summary(f"{prefix}{i}") for i in range(count)]


def card(sid, noise=None):
    return Incident(
        session_id=sid, step=1, signal=Signal.FAILED_COMMAND, what_happened="x", first_wrong="",
        cost_steps=0, what_fixed_it="", outcome=Outcome.NEVER_FIXED, noise=noise, topic="",
        files=(), situation=(), fingerprint="f", example="e",
    )  # fmt: skip


def build(sessions, topics, frictions=(), dates=None, incidents=()):
    topic_map = TopicMap(tuple(topics), tuple(frictions), ())
    return topic_view(topic_map, sessions, incidents, dates or {})


def test_outcomes_add_up_to_the_topics_sessions():
    sessions = [summary("a", DONE), summary("b", PARTLY), summary("c", STUCK), summary("d", DONE)]
    sessions += many(MIN_SUMMARIES)
    group = Group("Parser work", "d", ("a", "b", "c", "d"))
    shown = build(sessions, [group, Group("Rest", "r", tuple(s.session_id for s in many(30)))])
    topic = shown["topics"][0]
    assert topic["name"] == "Parser work"
    assert topic["outcomes"] == {"done": 2, "partly": 1, "stuck": 1, "unclear": 0}
    assert sum(topic["outcomes"].values()) == topic["sessions"] == len(topic["sessionList"]) == 4


def test_months_with_no_sessions_are_zero_not_missing():
    sessions = many(MIN_SUMMARIES)
    group = Group("Everything", "d", tuple(s.session_id for s in sessions))
    dates = {"s0": date(2026, 2, 3), "s1": date(2026, 5, 9)}
    shown = build(sessions, [group], dates=dates)
    assert shown["months"] == ["2026-02", "2026-03", "2026-04", "2026-05"]
    assert shown["topics"][0]["perMonth"] == [1, 0, 0, 1]
    assert shown["allPerMonth"] == [1, 0, 0, 1]
    assert shown["topics"][0]["first"] == "2026-02-03"
    assert shown["topics"][0]["last"] == "2026-05-09"
    assert shown["undated"] == MIN_SUMMARIES - 2


def test_friction_grid_counts_each_session_once_per_friction():
    sessions = many(MIN_SUMMARIES)
    ids = tuple(s.session_id for s in sessions)
    frictions = [Group("Lint", "d", ("s0", "s0", "s1")), Group("Env", "d", ("s1",))]
    shown = build(sessions, [Group("All", "d", ids)], frictions)
    topic = shown["topics"][0]
    assert topic["frictions"] == {"Lint": 2, "Env": 1}
    assert [f["name"] for f in shown["frictions"]] == ["Lint", "Env"]
    assert shown["frictions"][0]["sessions"] == 2


def test_noise_sessions_are_not_in_any_topic_and_are_counted():
    sessions = many(MIN_SUMMARIES) + [summary("junk", noise=True)]
    ids = tuple(s.session_id for s in sessions if not s.noise)
    shown = build(sessions, [Group("All", "d", ids)])
    assert shown["sessions"] == MIN_SUMMARIES
    assert shown["noiseSessions"] == 1


def test_below_the_threshold_topics_are_not_ready():
    shown = build([summary("a"), summary("b")], [])
    assert shown["ready"] is False
    assert shown["topics"] == []
    assert shown["needed"] == MIN_SUMMARIES - 2


def fact(sid, title, started):
    return SessionFacts(sid, title, frozenset(), frozenset(), 0, {}, False, started)


def test_sessions_by_date_come_from_session_facts_so_unsummarized_sessions_are_listed():
    facts = [fact("a", "Fix parser", "2026-03-01"), fact("b", "Add flag", "2026-03-09"),
             fact("u", "Old session", None)]  # fmt: skip
    shown = sessions_by_date(facts, [summary("a", STUCK)])
    assert [(s["id"], s["goal"], s["date"]) for s in shown] == [
        ("b", "Add flag", "2026-03-09"),
        ("a", "Fix parser", "2026-03-01"),
        ("u", "Old session", None),
    ]
    assert [s["outcome"] for s in shown] == [None, "stuck", None]


def test_each_topic_counts_its_incident_cards_without_noise():
    sessions = many(MIN_SUMMARIES)
    ids = tuple(s.session_id for s in sessions)
    cards = [card("s0"), card("s0"), card("s1", noise=object()), card("zzz")]
    shown = build(sessions, [Group("All", "d", ids)], incidents=cards)
    assert shown["topics"][0]["incidents"] == 2


def test_enough_summaries_but_no_topic_map_is_not_ready():
    shown = build(many(MIN_SUMMARIES + 5), [])
    assert shown["ready"] is False
    assert shown["needed"] == 0


def test_all_undated_history_has_no_months_and_counts_the_undated():
    sessions = many(MIN_SUMMARIES)
    shown = build(sessions, [Group("All", "d", tuple(s.session_id for s in sessions))])
    assert shown["months"] == []
    assert shown["topics"][0]["perMonth"] == []
    assert shown["topics"][0]["first"] is None
    assert shown["undated"] == MIN_SUMMARIES


def test_a_month_with_only_noise_sessions_is_still_a_zero_month_inside_the_range():
    sessions = many(MIN_SUMMARIES) + [summary("junk", noise=True)]
    ids = tuple(s.session_id for s in sessions if not s.noise)
    dates = {"s0": date(2026, 1, 5), "junk": date(2026, 2, 5), "s1": date(2026, 3, 5)}
    shown = build(sessions, [Group("All", "d", ids)], dates=dates)
    assert shown["months"] == ["2026-01", "2026-02", "2026-03"]
    assert shown["allPerMonth"] == [1, 0, 1]


def test_a_noise_only_month_at_the_edge_does_not_extend_the_axis():
    sessions = many(MIN_SUMMARIES) + [summary("junk", noise=True)]
    ids = tuple(s.session_id for s in sessions if not s.noise)
    dates = {"s0": date(2026, 2, 5), "junk": date(2026, 9, 5)}
    shown = build(sessions, [Group("All", "d", ids)], dates=dates)
    assert shown["months"] == ["2026-02"]


def test_a_topic_whose_members_are_all_noise_is_dropped():
    sessions = many(MIN_SUMMARIES) + [summary("junk", noise=True)]
    ids = tuple(s.session_id for s in sessions if not s.noise)
    topics = [Group("All", "d", ids), Group("Ghost", "d", ("junk",)), Group("Empty", "d", ())]
    shown = build(sessions, topics)
    assert [t["name"] for t in shown["topics"]] == ["All"]


def test_a_topic_the_developer_renamed_shows_the_new_name_and_keeps_its_stored_name_as_key():
    sessions = many(MIN_SUMMARIES)
    group = Group("Parser work", "d", tuple(s.session_id for s in sessions))

    shown = topic_view(
        TopicMap((group,), (), ()), sessions, (), {}, {"Parser work": "My <b>parser</b> topic"}
    )

    assert shown["topics"][0]["name"] == "My <b>parser</b> topic"
    assert shown["topics"][0]["key"] == "Parser work"


def test_the_dataset_readers_whose_history_no_session_model_sees_are_named(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine_a_session_without_failures(tmp_path, store, reader="swe-chat")
    assert topic_snapshot(store, "demo")["datasetReaders"] == ["swe-chat"]
    own = Store.open(tmp_path / "o.db")
    mine_a_session_without_failures(tmp_path, own, reader="claude-code")
    assert topic_snapshot(own, "demo")["datasetReaders"] == []
