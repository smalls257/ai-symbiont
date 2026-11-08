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

    said = "The agent ran pytest and it failed. Edited app.py."
    assert draft["when"] == "when running pytest on tests/e2e" and draft["what"] == said
    assert lesson["text_in_plain_words"] == f"When running pytest on tests/e2e: {said}"
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
        {"return_rule": "until_worse"},
        {"return_rule": "on_date"},
        {"return_rule": "never"},
    ]


def test_the_four_archive_choices_read_as_the_mockup_says_in_its_order(decided):
    assert decided["archiveLabels"] == [
        "Until it happens in 3 more sessions",
        "Until it gets worse",
        "For 30 days",
        "Forever",
    ]


def test_for_30_days_names_the_day_computed_from_the_given_today(decided):
    assert decided["archiveOn"][2] == "Comes back on Dec 7."


def test_no_view_or_an_unknown_one_opens_the_overview_with_one_warning(
    decided,
):
    assert decided["views"] == [
        "struggle", "inbox", "topics", "trends", "struggle", "context", "replay", "struggle"
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


def test_worth_sort_puts_a_shown_fix_first(decided):
    assert decided["worth"] == ["fixed", "loud"]


def test_review_folds_after_fifteen_rows_and_counts_the_rest(decided):
    pages = decided["pages"]

    assert pages["pageSize"] == 15
    assert len(pages["twenty"]["rows"]) == 15 and pages["twenty"]["more"] == 5
    assert len(pages["expanded"]["rows"]) == 20 and pages["expanded"]["more"] == 0
    assert len(pages["three"]["rows"]) == 3 and pages["three"]["more"] == 0


def test_scope_hint_shows_only_on_struggle(decided):
    assert decided["scope"] == [True, False, False, False, False, False]


def test_scope_hint_shows_only_for_struggle_inside_pain_points(decided):
    assert decided["scopeByStage"] == [False, True, False, False]
    assert not any(decided["scopeViewsOnOtherStages"])


def test_focus_after_show_more_lands_on_the_first_newly_revealed_row(decided):
    assert decided["focusAfterExpand"] == 15


def test_a_group_without_fix_shown_sorts_as_not_fixed(decided):
    assert decided["unmarkedWorth"] == ["fixedlow", "unmarked"]


def test_worth_a_look_is_the_default_and_the_first_sort_option(decided):
    assert decided["defaultSort"] == "worth"
    assert decided["sortOptions"][0] == "worth"
    assert decided["sortWords"]["worth"] == "Worth a look"


def test_orphan_triage_keys_are_ignored(decided):
    assert decided["orphanThrew"] == ""
    assert decided["orphan"] == decided["orphanPlain"]


def test_marking_a_group_taught_sends_the_id_the_lessons_store_gave_it(decided):
    body = decided["taughtBody"]

    assert body["taught"] is True and body["project"] == "demo"
    assert body["lesson_id"] == "lesson-9" and "lesson" not in body
    assert body["group_key"]


def test_badges_say_new_this_month_or_rising_and_an_unknown_badge_raises(decided):
    assert decided["badges"] == ["New this month", "Rising", ""]
    assert "unknown group badge" in decided["badBadge"]
    assert 'class="pill rising">Rising</span>' in decided["rowOpen"]


def test_the_verdict_is_the_sentence_when_there_is_one_else_the_word(decided):
    assert decided["verdicts"] == ["Worth a look: it costs time.", "fixed in the code"]
    assert "<dt>Worth a look</dt><dd>Worth a look: slow.</dd>" in decided["rowOpen"]


def test_a_row_is_focusable_and_has_a_visible_open_link_to_its_group(decided):
    row = decided["rowOpen"]

    assert 'tabindex="0"' in row
    assert 'data-route href="?project=my%20proj&amp;view=group&amp;key=many">Open</a>' in row
    assert 'data-a="teach"' in row


def test_tiles_carry_the_date_range_and_the_request_count_only_when_known(decided):
    assert decided["tiles"][0]["sub"] == "Oct 5 – Oct 20" and decided["tiles"][4]["sub"] == ""
    assert decided["tilesWithRequests"][4] == "from 12 summarizer requests"


def test_noise_rules_carry_why_returns_counts_and_examples_from_the_cards(decided):
    retry, acknowledged, mystery = decided["rules"]

    assert retry["count"] == 9 and retry["sessions"] == 1 and len(retry["examples"]) == 2
    assert retry["copy"]["returns"] == "Comes back if a retry stops passing."
    assert acknowledged["copy"]["returns"] == "Never returns."
    assert mystery["copy"] is None and mystery["examples"] == []
    assert decided["rulesFailureOnly"] == ["passed when run again", "mystery"]


def test_a_noise_reason_without_an_explanation_raises_instead_of_matching_nothing(decided):
    assert "no explanation for noise reason" in decided["unknownReason"]


def test_noise_rules_html_escapes_caps_and_links_each_example_to_its_session(decided):
    html = decided["rulesHtml"]

    assert "Show 2 real examples" in html and "<span>npm test &lt;b&gt;</span>" in html
    assert 'href="?project=demo&amp;view=session&amp;id=s1&amp;step=7">Oct 5</a>' in html
    assert "x" * 200 not in html and "…</span>" in html
    assert "No examples are in this snapshot." in html
    assert "Seen once: 2 groups (2 failed commands)" in html
    assert "Nothing was folded as noise" in decided["rulesEmpty"]


def test_the_seen_once_line_counts_groups_and_failed_commands(decided):
    line, empty = decided["seenOnce"]

    assert line.startswith("Seen once: 2 groups (3 failed commands)")
    assert "still count in topic outcomes" in line
    assert empty == ""


def test_friction_rows_are_biggest_first_with_a_share_tooltip_and_escaped_names(decided):
    rows = decided["frictions"]

    assert [r["name"] for r in rows] == ["Flaky", "Slow <i>CI</i>"]
    assert rows[0]["tip"] == "10 sessions of 40 (25%)" and rows[1]["width"] == 40
    assert decided["frictionsEmpty"] == []
    html = decided["frictionHtml"]
    assert "Slow &lt;i&gt;CI&lt;/i&gt;" in html and "<i>CI</i>" not in html
    assert "10 sessions of 40 (25%)" in html


def test_a_rule_with_thirty_cards_shows_twelve_of_thirty_then_all_thirty(decided):
    html = decided["bigHtml"]

    assert "Show 12 of 30 real examples" in html and "Show all 30" in html
    assert html.count("<li><a data-route") - 4 == 30  # four group links below


def test_every_noise_group_is_a_link_to_its_page_and_names_are_escaped(decided):
    html = decided["bigHtml"]

    assert "Evil &lt;b&gt;name&lt;/b&gt;" in html and "Evil <b>name</b>" not in html
    assert "key=big%20%3C1%3E" in html
    for key in decided["bigGroupKeys"]:
        assert (
            "view=group&amp;key=" + key.replace(" ", "%20").replace("<", "%3C").replace(">", "%3E")
            in html
        )
    assert "4 groups</summary>" in html


def test_the_story_lines_come_in_order_and_worth_a_look_only_when_a_sentence_exists(decided):
    story = decided["story"]
    labels = ["Working on", "What broke", "How it ended", "Worth a look"]
    positions = [story["full"].index(f"<dt>{label}</dt>") for label in labels]
    assert positions == sorted(positions)
    assert "vpill" not in story["full"]
    assert (
        "Worth a look" not in story["pill"]
        and 'class="pill vpill">fixed in the code' in story["pill"]
    )
    assert story["bare"].count("<dt>") == 1 and "Working on" not in story["bare"]
    assert "<dt>What you said</dt>" in story["correction"]
    assert "<dt>What the agent did next</dt>" in story["correction"]


def test_story_lines_are_escaped_and_backticks_become_code(decided):
    assert "<code>pnpm api:generate</code>" in decided["story"]["full"]
    hostile = decided["story"]["hostile"]
    assert (
        "<img" not in hostile
        and "&lt;img src=x onerror=1&gt;" in hostile
        and "<b>x</b>" not in hostile
    )


def test_a_teach_draft_says_what_broke_before_the_fix(decided):
    assert decided["brokeDraft"]["what"] == (
        "`git add a.ts` failed: Unable to create '.git/index.lock': File exists. "
        "Fixed the setup: ran `rm .git/index.lock`."
    )
