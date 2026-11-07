"""The group page: occurrence paging, the clearest pick, activity, topics, other groups, refusals.

Violation prevented: Paper Tiger (a page of 40 occurrences with no way to the one worth reading),
Silent Fallback (an unknown key opening another group; an invented activity event) and Leaky
Narrative (a Teach preview in wording the agent never hears; a command running as markup).
The snapshot comes from the production emitters; the page runs under node with a fake pane.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from symbiont.miner.incident_types import Incident, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.service.incident_view import incident_groups

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"
HOSTILE = "<img src=x onerror"
MAIN = "pytest"


def _incident(session, step, program=MAIN, fixed=True, topic="Parser work", example=None):
    return Incident(
        session_id=session, step=step, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed with ImportError.",
        first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed." if fixed else "",
        outcome=Outcome.FIXED_IN_CODE if fixed else Outcome.NEVER_FIXED, noise=None,
        topic=topic, files=("app.py",), situation=("running", program, "x"),
        fingerprint=f"failure:{program}:boom", example=example or f"{program} tests",
    )  # fmt: skip


def _correction(session, step):
    return Incident(
        session_id=session, step=step, signal=Signal.CORRECTION,
        what_happened="You told the agent to use uv, not pip.",
        first_wrong="Ran pip install", cost_steps=3,
        what_fixed_it="", outcome=Outcome.DEVELOPER_STEPPED_IN, noise=None, topic="Parser work",
        files=(), situation=("running", "pip", ""), fingerprint="", example="no, use uv",
    )  # fmt: skip


def _days():
    """Thirty sessions, one a day from Oct 1, so the main group spans three pages."""
    return {f"s{i}": f"2026-10-{i + 1:02d}" for i in range(30)} | {"c1": "2026-10-09"}


def _cards():
    main = [
        _incident(f"s{i}", i + 1, fixed=i % 7 != 0, topic="" if i < 6 else "Parser work")
        for i in range(30)
    ]
    main[29] = _incident("s29", 30, fixed=True, example="pytest " + "x" * 200, topic="Parser work")
    others = [
        _incident(f"s{i}", 50 + i, program=f"tool{n}") for n in range(7) for i in range(n + 1)
    ]
    return main + others + [_correction("c1", 4)]


def real_snapshot():
    days = _days() | {f"s{i}": f"2026-10-{i % 28 + 1:02d}" for i in range(30, 60)}
    incidents = incident_groups(_cards(), days)
    incidents["ownHistory"] = True
    summaries = [
        {
            "id": "s27",
            "date": "2026-10-28",
            "goal": "Fix the parser",
            "outcome": "done",
            "friction": "",
        }
    ]
    topics = [{"key": "t1", "name": "Parser work", "sessionList": summaries}]
    return {
        "incidents": incidents,
        "topicView": {"topics": topics},
        "triage": {},
        "stage": {"facts": list(range(60))},
    }


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    snapshot = tmp_path_factory.mktemp("snap") / "snapshot.json"
    snapshot.write_text(json.dumps(real_snapshot()), encoding="utf-8")
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "group_harness.js"), str(STATIC), str(snapshot)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    return json.loads(out.stdout)


def test_the_real_cards_carry_what_the_page_reads():
    card = real_snapshot()["incidents"]["groups"][0]["cards"][0]

    for field in (
        "step",
        "command",
        "topic",
        "sessionId",
        "happened",
        "fixed",
        "outcome",
        "session",
    ):
        assert field in card


def test_the_page_registers_as_the_group_detail_view(page):
    assert page["registered"] == "group"


def test_twelve_occurrences_a_page_newest_first(page):
    html = page["firstPage"]

    assert html.count('class="occ2') == 12
    assert html.index("Oct 30") < html.index("Oct 19") and "Oct 18" not in html.split("Oct 19")[0]


def test_older_and_newer_page_through_all_thirty(page):
    assert "Oct 18" in page["secondPage"] and "Oct 30" not in page["secondPage"]
    assert "page 2 of 3" in page["secondNav"]


def test_first_jumps_to_the_oldest_page_and_latest_back(page):
    assert 'class="d">Oct 1<a' in page["firstJump"] and "Oct 30" not in page["firstJump"]
    assert "page 3 of 3" in page["firstNav"] and "Older ›</button>" in page["firstNav"]
    assert page["firstNav"].count("disabled") == 1
    assert "Oct 30" in page["latestJump"]
    assert 'data-occ="newer" disabled' in page["newerAtStart"]


def test_the_clearest_example_is_a_real_fix_with_a_short_command_and_the_latest_of_equals(page):
    assert page["model"]["pick"] == 3  # not 1: its command is too long; not 0: no fix
    assert page["clearestJump"].count("clearest example</span>") == 1
    marked = page["clearestJump"].split('occ2 rec"')[1].split("</dl>")[0]
    assert "$ pytest tests" in marked and "$ pytest xxxx" not in marked and "Oct 28" in marked


def test_each_occurrence_links_to_its_session_at_the_step_and_shows_goal_and_outcome(page):
    marked = page["clearestJump"]

    assert "?project=my%20repo&amp;view=session&amp;id=s27&amp;step=28" in marked
    assert "Fix the parser" in marked and "o-done" in marked and ">done<" in marked


def test_an_unsummarized_session_shows_no_outcome_chip(page):
    assert (
        page["firstPage"].count('class="outc"') == 1
    )  # only s27 has a summary; 11 others show none


def test_verdict_lines_say_same_as_the_group_or_unresolved(page):
    assert "Same as the group:" in page["firstPage"] and "Unresolved here:" in page["secondPage"]


def test_the_header_names_the_group_and_its_facts(page):
    head = page["head"]

    assert "e.g. pytest xxxx" in head and "Grouped because:" in head
    assert (
        "<b>30</b>time" in head
        and "<b>30</b>sessions of 60" in head
        and "<b>Oct 1</b>first seen" in head
    )
    assert "<b>Oct 30</b>last seen" in head and "<b>Parser work</b>topic with most of it" in head
    for word in ("Teach the agent", "Mark reviewed", "Resolve", "Archive, and bring it back"):
        assert word in head


def test_the_weekly_chart_has_bars_a_y_axis_week_labels_and_the_tooltip(page):
    chart = page["timeline"]

    assert "<svg" in chart and 'text-anchor="end">0</text>' in chart
    assert "Week of Sep 28" in chart and "sessions that week" in chart and "7 times" in chart
    assert 'class="mark"' not in chart


def test_a_taught_lesson_draws_the_dashed_marker_and_says_update(page):
    assert (
        'class="mark"' in page["timelineTaught"] and "lesson added Oct 12" in page["timelineTaught"]
    )
    assert "Update lesson" in page["teachTaught"] and "Lesson added on Oct 12" in page["headTaught"]


def test_three_lines_say_what_happened_what_fixed_it_and_the_verdict(page):
    for word in ("What happened", "What fixed it", "Verdict"):
        assert word in page["three"]


def test_the_teach_panel_is_prefilled_and_shows_the_note_the_agent_receives(page):
    assert 'value="when running pytest' in page["teach"] or "when running" in page["teach"]
    assert "Plain sentences only" in page["teach"]
    assert page["preview"].startswith('<span class="user">[symbiont] In this repo: ')


def test_the_preview_uses_the_real_note_wording_by_kind(page):
    model = page["model"]

    assert model["house"] == (
        "[symbiont] House rules for this repo (from your corrections and PR reviews): Use uv."
    )
    assert model["repo"] == "[symbiont] In this repo: Run uv sync first."
    assert model["cut"] < 700 and "..." in page["model"]["repo"] + "..."


def test_editing_the_lesson_updates_the_preview_and_saving_posts_the_lesson_then_the_day(page):
    assert "Run uv sync first." in page["preview"]
    lesson, triage = page["saveCalls"]
    assert (
        lesson[0] == "/lessons/add"
        and "Run uv sync first." in lesson[1]["lessons"][0]["text_in_plain_words"]
    )
    assert (
        triage[0] == "/triage"
        and triage[1]["taught"] is True
        and triage[1]["lesson_id"] == "lesson-9"
    )
    assert page["savedLabel"] == "Update lesson"


def test_mark_reviewed_and_archive_post_the_same_triage_bodies_as_the_inbox(page):
    assert page["reviewedCalls"] == [
        [
            "/triage",
            {
                "project": "my repo",
                "group_key": page["reviewedCalls"][0][1]["group_key"],
                "state": "reviewed",
            },
        ]
    ]
    state = page["archiveCalls"][0][1]
    assert (
        state["state"] == "archived"
        and state["return_rule"] == "after_sessions"
        and state["after_sessions"] == 3
    )


def test_teach_button_scrolls_to_the_panel_and_focuses_the_textarea(page):
    assert page["plainFocus"][0] == 1 and "#gWhat" in page["plainFocus"][1]


def test_a_teach_hash_scrolls_flashes_and_focuses(page):
    scrolled, classes, focused = page["teachHash"]

    assert scrolled == 1 and classes == ["spot"] and "#gWhat" in focused


def test_activity_lists_only_what_the_store_recorded(page):
    quiet = page["activityQuiet"]

    assert "Grouped from 30 sessions" in quiet and "Last seen" in quiet
    assert "Lesson added" not in quiet and "Moved to" not in quiet and "nightly" not in quiet
    taught = page["activityTaught"]
    assert "Moved to Archived. Comes back if it shows up clearly more often" in taught
    assert "Oct 20 · you" in taught and "Lesson added" in taught and "Oct 12 · you" in taught
    assert "Fix the parser" not in quiet


def test_a_regressed_group_says_it_happened_again(page):
    assert "It happened again after you set it aside" in page["activityRegress"]
    assert "Regressed" in page["headRegress"]


def test_topics_show_sessions_per_topic_with_a_link_and_other_for_no_topic(page):
    topics = page["topics"]

    assert "view=topics&amp;t=t1" in topics and "<b>24</b>" in topics
    assert "Other" in topics and "<b>6</b>" in topics and "Numbers are sessions." in topics


def test_other_groups_are_the_same_kind_top_five_by_sessions(page):
    others = page["others"]

    assert others.count("<a ") == 5 and "7 sessions" in others and "view=group" in others
    assert "no, use uv" not in others and "30 sessions" not in others


def test_an_unknown_key_says_no_such_group_with_a_way_back_and_opens_nothing_else(page):
    assert "No such group: nope" in page["missing"] and "Back to the inbox" in page["missing"]
    assert "Every occurrence" not in page["missing"] and "Fix the parser" not in page["missing"]


def test_a_hostile_key_and_a_hostile_name_are_text(page):
    assert HOSTILE not in page["hostileKey"] and "&lt;img src=x onerror" in page["hostileKey"]
    assert HOSTILE not in page["hostile"] and "&lt;img src=x onerror" in page["hostile"]


def test_the_crumb_names_the_kind_and_group(page):
    assert page["crumbs"][0].startswith("Agent failure: ")


def test_a_correction_shows_what_the_agent_had_done_and_your_words_for_any_history(page):
    for key in ("corr", "corrDataset"):
        assert "You: “no, use uv”" in page[key] and "Agent had just: " in page[key]
        assert "e.g. no, use uv" in page[key]
    assert "House rules for this repo" in page["corr"]


def test_a_triage_click_on_the_group_page_reaches_the_inbox_counts(page):
    inbox = page["inbox"]

    assert inbox["reviewedBefore"] == 0 and inbox["reviewedAfter"] == 1
    assert inbox["changed"] >= 1  # the shared action told the views to redraw the Inbox


def test_weeks_are_bars_rising_from_the_axis_not_the_dashboard_progress_bar(page):
    chart = page["timeline"]

    assert 'class="wk"' in chart and 'class="bar"' not in chart
    assert (
        'y="150"' not in chart.split('class="wk"')[1].split(">")[0]
    )  # a bar's top is above the baseline
