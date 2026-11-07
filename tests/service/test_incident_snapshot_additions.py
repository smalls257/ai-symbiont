"""What the group, session and topic pages read from `incidents` beyond the Inbox's needs."""

import json
from dataclasses import replace

from symbiont.miner.incident_types import Incident, Outcome
from symbiont.miner.incident_words import command_example
from symbiont.miner.painpoint import Signal
from symbiont.service.incident_view import IncidentContext, incident_groups

LONG_COMMAND = "uv run pytest tests/service/test_incident_view.py -x -q --maxfail=2 -k parser"
FILES = ("src/symbiont/service/incident_view.py", "tests/service/test_x.py", "pyproject.toml")
SESSION_TITLE = "Fix the parser so that nested quotes survive a round trip"
TOKEN = "ghp_" + "a1B2" * 9
DAYS = {"a": "2026-10-05", "b": "2026-10-06", "c": "2026-10-20", "d": "2026-08-01", "u": None}


def card(session, step=1, topic="", program="pytest", example="pytest tests"):
    return Incident(
        session_id=session, step=step, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed.", outcome=Outcome.FIXED_IN_CODE,
        noise=None, topic=topic, files=("app.py",), situation=("running", program, "tests"),
        fingerprint=f"failure:{program}:boom", example=example,
    )  # fmt: skip


def test_a_card_tells_its_step_command_and_topic():
    shown = incident_groups([card("a", step=7, topic="Parser", example="pytest -x")], DAYS)
    only = shown["groups"][0]["cards"][0]
    assert (only["step"], only["command"], only["topic"]) == (7, "pytest -x", "Parser")
    assert shown["noTopic"] == []


def test_a_command_with_a_token_reaches_the_card_scrubbed():
    example = command_example(f"curl -H 'Authorization: token {TOKEN}' https://example.test/x")
    shown = incident_groups([card("a", example=example)], DAYS)
    assert TOKEN not in json.dumps(shown)
    assert "[secret]" in shown["groups"][0]["cards"][0]["command"]


def test_sessions_per_week_covers_every_week_of_a_groups_weekly_series():
    shown = incident_groups([card("a"), card("c"), card("d")], DAYS)
    axis = dict(map(tuple, shown["sessionsPerWeek"]))
    weekly = shown["groups"][0]["weekly"]
    assert all(week in axis for week, _ in weekly)
    assert list(axis) == sorted(axis) and axis["2026-W41"] == 2  # sessions a and b
    assert sum(axis.values()) == 4  # the undated session is on no week


def test_a_group_first_seen_within_a_month_of_the_newest_session_is_badged_new():
    shown = incident_groups([card("c"), card("a")], DAYS)
    assert shown["groups"][0]["badge"] == "new"
    old = incident_groups([card("d"), card("a")], DAYS)
    assert old["groups"][0]["badge"] is None


def test_the_additions_grow_the_incidents_block_by_less_than_15_percent():
    cards = [
        replace(
            card(f"s{i}", step=i, topic="Parser and build work", example=LONG_COMMAND), files=FILES
        )
        for i in range(300)
    ]
    days = {f"s{i}": f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}" for i in range(300)}
    context = IncidentContext(titles={c.session_id: SESSION_TITLE for c in cards})
    after = incident_groups(cards, days, context)
    assert len(json.dumps(after)) < 1.15 * len(json.dumps(_without_additions(after)))


def test_no_card_is_listed_twice_topics_and_no_topic_only_point_at_cards():
    cards = [card("a", topic="Parser"), card("c"), card("b", topic="Parser")]
    shown = incident_groups(cards, DAYS)
    refs = shown["topics"][0]["worth"] + shown["noTopic"]
    assert [(r["sessionId"], r["step"]) for r in refs] == [("b", 1), ("a", 1), ("c", 1)]
    assert all("happened" not in r and "command" not in r for r in refs)
    listed = [(c["sessionId"], c["step"]) for g in shown["groups"] for c in g["cards"]]
    assert sorted(listed) == sorted((r["sessionId"], r["step"]) for r in refs)


def _without_additions(shown):
    """The snapshot as it was before this task: no new fields, topics holding card copies."""
    before = json.loads(json.dumps(shown))
    del before["sessionsPerWeek"]
    copies = {}
    for group in before["groups"]:
        del group["badge"]
        for each in group["cards"]:
            copies[(each["sessionId"], each["step"])] = {
                k: v for k, v in each.items() if k not in ("step", "command", "topic")
            }
            for key in ("step", "command", "topic"):
                del each[key]
    for topic in before["topics"]:
        topic["worth"] = [copies[(r["sessionId"], r["step"])] for r in topic["worth"]]
    before["noTopic"] = [copies[(r["sessionId"], r["step"])] for r in before["noTopic"]]
    return before
