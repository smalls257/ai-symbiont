"""The Inbox's rules: what is For review, what folds, what Teach sends, which view a link opens.

Violation prevented: Paper Tiger. An inbox that lists every group (or hides some without a count)
meets "show the groups" and fails "what is worth my time". The pure functions of inbox_model.js
and inbox_rows.js run under node with no DOM; node is a hard requirement here as for the JS gate.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"


@pytest.fixture(scope="module")
def decided():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "inbox_harness.js"), str(STATIC)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_only_recurring_groups_are_for_review_and_the_rest_fold_into_counted_sections(decided):
    plain = decided["plain"]

    assert plain["review"] == ["many", "corr"] and plain["once"] == ["once"]
    assert plain["noise"] == ["noisy", "noisy2"]
    assert decided["correctionsOnly"] == ["corr"]


def test_all_archived_groups_show_with_the_noise_and_not_an_empty_list(decided):
    shown = decided["allArchived"]

    assert shown["review"] == [] and shown["once"] == []
    assert sorted(shown["archived"]) == ["corr", "many", "once"]
    assert shown["noise"] == ["noisy", "noisy2"]


def test_noise_is_counted_per_reason_with_its_nouns(decided):
    assert decided["noiseReasons"] == [
        {"reason": "passed when run again", "groups": 2, "times": 7, "sessions": 3}
    ]


def test_a_saved_name_wins_over_the_generated_one_and_an_unknown_state_is_refused_loudly(decided):
    assert decided["renamed"] == "Mine" and decided["generated"] == "Name of many"
    assert "unknown triage state" in decided["badState"] and "many" in decided["badState"]


def test_a_name_is_trimmed_and_at_most_80_characters(decided):
    assert decided["trimmed"] == "Flaky"
    assert "80" in decided["tooLong"]


def test_every_tile_label_is_a_noun_and_the_counts_are_the_groups(decided):
    labels = [(t["value"], t["label"]) for t in decided["tiles"]]

    assert labels == [
        (3, "sessions read"),
        (12, "failed commands"),
        (4, "messages from you"),
        (2, "groups for review"),
        (2, "topics"),
    ]
    assert decided["tiles"][3]["sub"] == "of 5 groups found"


def test_weekly_bars_share_one_axis_with_a_zero_for_a_quiet_week(decided):
    assert decided["axisKeys"] == ["2026-W41", "2026-W42", "2026-W43"]
    assert decided["series"] == [2, 0, 2]


def test_teach_the_agent_is_prefilled_from_the_trigger_and_the_fix_and_sends_applies_to(decided):
    draft, request = decided["draft"], decided["request"]
    lesson = request["lessons"][0]

    assert draft["when"] == "when running pytest on tests/e2e" and draft["what"] == "Edited app.py."
    assert lesson["text_in_plain_words"] == "When running pytest on tests/e2e: Edited app.py."
    assert lesson["applies_to"] == {"terms": ["pytest"], "areas": ["tests/e2e"]}
    assert lesson["kind"] == "mistake" and request["project"] == "demo"


def test_teach_still_saves_when_the_group_has_no_trigger_and_nothing_was_typed(decided):
    lesson = decided["bare"]["lessons"][0]

    assert "applies_to" not in lesson
    assert lesson["text_in_plain_words"] == "The agent ran pytest and it failed."
    assert lesson["kind"] == "correction"
    assert decided["corrDraft"]["hasTrigger"] is False


def test_the_dialog_says_it_trains_only_when_the_server_says_the_lesson_behind_it_does(decided):
    assert decided["draft"]["trains"] is True
    assert decided["neverFixed"]["trains"] is False and decided["neverFixed"]["what"] == ""
    assert decided["corrDraft"]["trains"] is False
    assert decided["teachNotes"]["trains"] == (
        "The mined lesson behind this group feeds nightly training; "
        "your note is delivered to the agent."
    )
    assert decided["teachNotes"]["held"] == (
        "Delivered to the agent as a note; it does not feed nightly training."
    )


def test_a_correction_is_quoted_as_you_said_only_in_the_developers_own_history(decided):
    assert decided["corrDraftOwn"]["what"].startswith("You said: ")
    assert "You said" not in decided["corrDraft"]["what"]


def test_an_empty_what_falls_back_to_what_happened_so_a_lesson_is_never_only_a_trigger(decided):
    text = decided["emptyWhat"]["lessons"][0]["text_in_plain_words"]
    assert text == "When running pytest: The agent ran pytest and it failed."


def test_archive_asks_for_a_return_condition_the_service_knows(decided):
    assert decided["archive"] == [
        {"return_rule": "after_sessions", "after_sessions": 3},
        {"return_rule": "new_session"},
        {"return_rule": "never"},
    ]


def test_the_view_parameter_picks_the_view_and_an_unknown_one_opens_the_inbox_with_one_warning(
    decided,
):
    assert decided["views"] == [
        "inbox", "inbox", "topics", "trends", "struggle", "context", "replay", "inbox"
    ]  # fmt: skip
    assert len(decided["warnings"]) == 1 and "nope" in decided["warnings"][0]


def test_a_row_escapes_the_name_says_regressed_and_shows_the_episode_of_a_correction(decided):
    failure, correction = decided["rowFailure"], decided["rowCorr"]

    assert "A &lt;b&gt;name&lt;/b&gt;" in failure and "<b>name</b>" not in failure
    assert "Regressed" in failure and "4 times" in failure and "3<small>sessions</small>" in failure
    assert "Where it went wrong" in correction and "Ran pip install" in correction
    assert "4 agent steps before you stepped in" in correction
    assert "Lesson added on Nov 1." in correction and "Move to For review" in correction
    assert "shows here again" not in correction
    assert "149 sessions without a date" in failure


def test_a_tooltip_keeps_its_formatting_tags_and_turns_every_other_tag_into_text(decided):
    plain, img, onclick, script, escaped = decided["tips"]

    assert plain == "<b>Week of Oct 5</b><br>1 time"
    assert "<img" not in img and "&lt;img src=x onerror=window.__x=1>" in img
    assert onclick.startswith("&lt;b onclick=") and "<script" not in script
    assert "<span class=m>quiet</span>" in script and escaped == "&lt;img src=x&gt; already escaped"


def test_a_group_kind_cannot_break_out_of_the_class_attribute(decided):
    assert 'class="kmark x&quot; onmouseover=&quot;window.__x=1"' in decided["rowEvil"]
