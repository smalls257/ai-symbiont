"""Topic examples and weekly series: they add up to the topic's sessions and share one axis."""

from datetime import date, timedelta

from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.topics import Group, TopicMap
from symbiont.service.topic_view import MIN_SUMMARIES, topic_view


def summaries(count, goal=lambda i: f"goal {i}"):
    return [SessionSummary(f"s{i}", goal(i), SummaryOutcome.DONE, "", False) for i in range(count)]


def built(sessions, dates):
    ids = tuple(s.session_id for s in sessions)
    topics = TopicMap((Group("Everything", "d", ids),), (), ())
    return topic_view(topics, sessions, [], dates)


def spread(count):
    return {f"s{i}": date(2026, 10, 5) + timedelta(days=10 * i) for i in range(count)}


def test_examples_are_the_first_three_distinct_goals_newest_first():
    goals = {0: "old", 1: "", 2: "dup", 3: "dup", 4: "newest"}
    sessions = summaries(MIN_SUMMARIES, lambda i: goals.get(i, "dup"))
    dates = spread(MIN_SUMMARIES)
    dates["s4"] = date(2030, 1, 1)
    assert built(sessions, dates)["topics"][0]["examples"] == ["newest", "dup", "old"]


def test_weekly_series_sum_to_the_sessions_and_share_the_weeks_axis():
    sessions, dates = summaries(MIN_SUMMARIES), spread(MIN_SUMMARIES)
    shown = built(sessions, dates)
    topic = shown["topics"][0]
    assert len(shown["weeks"]) == len(shown["allPerWeek"]) == len(topic["perWeek"])
    assert sum(shown["allPerWeek"]) == sum(topic["perWeek"]) == topic["sessions"]
    assert shown["weeks"][0] == "2026-W41" and 0 in topic["perWeek"]


def test_a_store_that_keeps_no_batch_boundaries_says_null_requests():
    assert built(summaries(MIN_SUMMARIES), spread(MIN_SUMMARIES))["requests"] is None


def test_no_dated_session_means_no_weeks_and_an_empty_series():
    shown = built(summaries(MIN_SUMMARIES), {})
    assert shown["weeks"] == [] and shown["allPerWeek"] == []
    assert shown["topics"][0]["perWeek"] == []
