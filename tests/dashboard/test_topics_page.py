"""The Topics page and the Inbox topic panel against their mockups, drawn under node.

Violation prevented: Paper Tiger (a page that lists topics but cannot answer "how often does
this kind of work end done" or "what went wrong in it") and Silent Fallback (an unknown `t`
quietly showing another topic).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"


@pytest.fixture(scope="module")
def drawn():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "topics_harness.js"), str(STATIC)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_topics_list_most_sessions_first_and_a_one_session_topic_is_not_a_row(drawn):
    assert drawn["mainOrder"] == ["Docs", "Parser work", "Slow CI"]


def test_the_least_often_done_sort_puts_the_hardest_work_first(drawn):
    assert drawn["hardOrder"] == ["Slow CI", "Docs", "Parser work"]
    assert 'data-sort="hard" aria-pressed="true"' in drawn["hardHtml"]


def test_rows_say_percent_done_with_the_range_and_scale_bars_only_when_sorted_by_sessions(drawn):
    assert "83% done · Mar 2 – Mar 16" in drawn["main"]
    assert 'class="ob" style="width:100%"' in drawn["main"]
    assert 'class="ob" style="width:44%"' in drawn["main"]
    assert 'class="ob" style="width:100%"' in drawn["hardHtml"]
    assert 'style="width:44%"' not in drawn["hardHtml"]


def test_sub_copy_names_the_requests_only_when_they_are_known(drawn):
    assert (
        "3 topics named by the model from 40 one-line session summaries,"
        " made in 3 requests. Click one." in drawn["main"]
    )
    assert "made in" not in drawn["noRequests"]


def test_what_went_wrong_lists_the_topics_groups_by_count_with_links(drawn):
    html = drawn["asked"]
    wrong = html[html.index("What went wrong here") :]

    assert wrong.index("pytest fails") < wrong.index("You said no")
    assert "3 times" in wrong and "2 messages" in wrong
    assert "view=group&amp;key=g1" in wrong and "noisy" not in wrong


def test_what_went_wrong_keeps_the_top_eight_and_uses_the_developers_group_name(drawn):
    wrong = drawn["asked"][drawn["asked"].index("What went wrong here") :]
    named = drawn["renamed"][drawn["renamed"].index("What went wrong here") :]

    assert (
        len(re.findall(r'<a data-route href="[^"]*view=group', wrong.split("<h3>Sessions")[0])) == 8
    )
    assert "Renamed group" in named


def test_typical_goals_and_goal_cells_link_to_the_session(drawn):
    assert "<li>goal one</li>" in drawn["asked"]
    assert 'view=session&amp;id=s0">goal 0</a>' in drawn["asked"]
    assert "Goal (model summary)" in drawn["asked"] and "a slow test" in drawn["asked"]


def test_weekly_rows_start_with_an_all_sessions_row_and_a_shared_axis(drawn):
    html = drawn["main"]
    weekly = html[html.index("Topics over time") : html.index("Where each topic got stuck")]

    assert weekly.index("All sessions") < weekly.index("Docs")
    assert "Mar 2" in weekly and "Mar 16" in weekly
    assert weekly.count("<svg") == 4
    assert "week of Mar 9" in weekly and "of 20 that week" in weekly


def test_the_friction_grid_has_an_all_topics_row_and_sorts_by_sessions(drawn):
    html = drawn["main"]
    grid = html[html.index("Where each topic got stuck") :]

    assert "All topics <small>40</small>" in grid and "8 sessions of 40 (20%)" in grid


def test_picking_a_topic_writes_t_with_replace_state_and_selects_it(drawn):
    assert drawn["pickedUrl"] == "?project=p&view=topics&t=Slow%20CI"
    assert "<h2><button" in drawn["pickedHtml"] and "Slow CI</button> <span" in drawn["pickedHtml"]
    assert 'data-topic="Slow CI" aria-pressed="true"' in drawn["pickedHtml"]


def test_a_link_can_move_the_selection_and_the_asked_topic_opens(drawn):
    for html in (drawn["selected"], drawn["asked"]):
        assert 'data-topic="Slow CI" aria-pressed="true"' in html
        assert 'data-topic="Docs" aria-pressed="true"' not in html


def test_an_unknown_t_is_a_not_found_note_in_the_detail_column_never_another_topic(drawn):
    html = drawn["unknown"]
    detail = html[html.index('class="panel det"') :].split("</section>")[0]

    assert "No such topic" in detail and "Nope &lt;b&gt;" in detail and "Nope <b>" not in html
    assert (
        'aria-pressed="true" data-topic' not in html
        and 'data-topic="Docs" aria-pressed="true"' not in html
    )
    assert "Typical goals" not in detail
    assert "view=topics" in detail


def test_the_inbox_panel_links_to_the_page_and_folds_open_to_goals(drawn):
    html = drawn["compact"]

    assert "Topics in detail" in html and "view=topics" in html
    assert "83% done" in html and "Mar 2 – Mar 16" in html
    assert "All 9 sessions, outcomes and friction" in html and "view=topics&amp;t=Docs" in html
    assert 'aria-expanded="false"' in html and 'aria-expanded="true"' not in html
    assert 'aria-expanded="true"' in drawn["compactOpen"]


def test_the_inbox_panel_lists_one_session_topics_and_noise_in_one_line(drawn):
    assert "One-off: 1 session · 4 sessions with no real task (noise)" in drawn["compact"]
    assert (
        "4 topics from one-line summaries of all 40 sessions (3 model requests)" in drawn["compact"]
    )


def test_hostile_text_stays_text_everywhere(drawn):
    html = drawn["hostile"]

    assert "<img src=x onerror" not in html and "<b>g</b>" not in html and "<u>grp</u>" not in html
    assert "&lt;img src=x onerror=1&gt;" in html and "&lt;b&gt;g&lt;/b&gt;" in html
