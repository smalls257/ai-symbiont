"""Topics and "Is it getting better?": what they say with no data, and that stored text stays text.

Violation prevented: Silent Fallback (a dataset history told to run a command that cannot work, a
store with no dates blamed on the history) and Leaky Narrative at the page boundary (a topic name
or lesson title running as markup). The renderers run under node with a fake container.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"
HOSTILE = "<img src=x onerror"


@pytest.fixture(scope="module")
def drawn():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "views_harness.js"), str(STATIC)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_a_dataset_history_says_why_it_has_no_topics_instead_of_asking_for_a_summary(drawn):
    html = drawn["datasetNotReady"]

    assert "swe-chat" in html and "never shown to a session model" in html
    assert "/symbiont summarize" not in html and "more session summaries needed" not in html


def test_the_sessions_by_date_list_shows_every_session_even_with_no_summaries(drawn):
    for html in (drawn["datasetNotReady"], drawn["ownNotReady"]):
        assert "Fix the parser" in html and "Older work" in html and "Mar 9" in html


def test_one_own_history_still_gets_the_instruction(drawn):
    assert "/symbiont summarize" in drawn["ownNotReady"]


def test_a_hostile_topic_name_renders_as_text(drawn):
    html = drawn["hostileTopic"]

    assert HOSTILE not in html and "&lt;img src=x onerror" in html


def test_a_hostile_replay_lesson_title_stays_inert_after_the_tooltip_sanitizer(drawn):
    assert "<img" not in drawn["replayTip"] and "&lt;img src=x onerror" in drawn["replayTip"]


def test_no_dated_session_is_one_sentence_not_a_table_of_no_dates_rows(drawn):
    old, truly = drawn["noDatesOld"], drawn["noDatesTruly"]

    assert "mined before session dates were kept" in old and "mine this repository again" in old
    assert "carries no timestamps" in truly and "mined before" not in truly
    assert "no dates" not in old + truly and 'class="mt"' not in old + truly


def test_the_undated_note_blames_the_old_mining_only_for_an_old_store(drawn):
    assert "mined before session dates were kept; mine again" in drawn["oldNote"]
    assert "their history carries no timestamps" in drawn["trulyNote"]
    assert "mined before" not in drawn["trulyNote"]


def test_occurrences_outside_the_twelve_months_are_counted(drawn):
    assert "4 more occurrences fall outside the last 12 months" in drawn["outside"]


def test_a_gone_group_with_no_last_day_and_a_hostile_title_still_draws_safely(drawn):
    html = drawn["goneNoLast"]

    assert HOSTILE not in html and "&lt;img src=x onerror" in html and ">gone<" in html


def test_a_trend_with_too_few_occurrences_says_so(drawn):
    assert "too few to tell" in drawn["tooFew"]


def test_route_round_trip_hostile_keys(drawn):
    for case, key in zip(drawn["routing"]["roundTrip"], drawn["routing"]["hostile"], strict=True):
        assert case["back"] == {"view": "group", "key": key, "hash": "teach me"}
        assert case["href"].startswith("?project=my%20proj&view=group&key=")
        assert "&" not in case["href"].split("key=")[1].split("#")[0]


def test_group_without_key_is_notfound(drawn):
    html = drawn["routing"]["missing"]

    assert "No such group." in html and 'href="?project=p&view=inbox"' in html
    assert drawn["routing"]["notFoundView"] == "notfound"


def test_session_step_is_integer(drawn):
    assert drawn["routing"]["steps"] == [None, 12, None, None, None]


def test_unknown_view_warns_once(drawn):
    routing = drawn["routing"]

    assert routing["unknown"] == {"view": "inbox"}
    assert len([w for w in routing["warnings"] if "unknown view" in w]) == 1


def test_popstate_restores_the_view_and_clears_the_crumb(drawn):
    routing = drawn["routing"]

    assert routing["afterPop"] == {"view": "topics", "crumb": "", "crumbHidden": True}
    assert routing["crumbA"] == "Group a"


def test_navigation_pushes_history_and_redraws_detail_views_each_time(drawn):
    routing = drawn["routing"]

    assert routing["afterNavigate"] == {"view": "session", "url": "?project=p&view=session&id=s1"}
    assert routing["unbuilt"] == '<p class="soon" role="status">Not built yet.</p>'
    assert [c["route"]["key"] for c in routing["calls"]] == ["a", "b", "c:d"]
    assert all(c["project"] == "p" and c["same"] for c in routing["calls"])
    assert routing["groupPane"] == "G:c:d"


def test_only_a_plain_left_click_on_a_route_link_navigates(drawn):
    routing = drawn["routing"]

    assert routing["plain"] is True
    assert routing["ctrl"] is False and routing["middle"] is False
    assert routing["pushedBeforePop"] == 4


def test_the_header_meta_line_gives_scale_and_privacy(drawn):
    assert drawn["routing"]["meta"] == "3 sessions · Jan 5, 2026 – Apr 2, 2026 · local only"


def test_a_row_name_links_to_its_group_page_with_the_key_encoded(drawn):
    html = drawn["linked"]

    assert '<a data-route href="?project=my%20proj&amp;view=group&amp;key=a%26b%20c"' in html


def test_the_grid_and_a_sticky_side_column_share_one_row(drawn):
    html = drawn["found"]

    assert 'class="pg"' in html and '<aside class="side">' in html
    assert "30rem" in html and "position:sticky" in html


def test_lessons_show_their_words_a_link_and_the_after_wait_or_rate(drawn):
    html = drawn["lessons"]

    assert "Unset the token first." in html and "added 5 Mar 2026" in html
    assert "after: waiting for 6 more sessions" in html
    assert "after: 0.8 per 10 sessions" in html
    assert HOSTILE not in html and "&lt;img src=x onerror" in html


def test_a_lesson_whose_words_are_gone_says_so_and_never_shows_the_group_title_instead(drawn):
    html = drawn["lessonGone"].split("Lessons you added")[1]

    assert "Lesson text not available (removed or taught before this version)" in html
    assert "Group title" not in html


def test_no_lessons_says_how_to_add_one(drawn):
    assert 'Use "Teach the agent"' in drawn["noLessons"]


def test_a_found_before_and_after_carries_the_caveat_and_a_link_to_its_group(drawn):
    html = drawn["found"]

    assert "A before and after you already have" in html and "Not taught through symbiont" in html
    assert "can also make a group go quiet" in html and "at least 10 sessions" in html
    assert "5 failures in 2 sessions" in html
    assert "0 failures in 14 sessions after 2 Mar 2026" in html
    assert 'href="?project=my%20proj&amp;view=group&amp;key=n1"' in html


def test_no_found_before_and_after_leaves_the_panel_out(drawn):
    assert "A before and after you already have" not in drawn["noLessons"]


def test_a_hostile_found_group_stays_text(drawn):
    html = drawn["foundHostile"]

    assert HOSTILE not in html and "&lt;img src=x onerror" in html
