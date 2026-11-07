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
