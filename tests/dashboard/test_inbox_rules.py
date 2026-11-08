"""The Inbox's "Rules you've stated" section under node, with the real shared triage actions.

Failures guarded against: Distributed Monolith (a second Teach or archive path), Leaky Narrative
(an unconfirmed rule that reads as a fact), and an unescaped rule or quote reaching innerHTML.
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
def shown():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "rules_harness.js"), str(STATIC)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_a_confirmed_row_says_the_rule_how_often_and_when_and_links_each_quote_to_its_step(shown):
    html = shown["html"]
    assert "<b>Use pnpm, not npm.</b>" in html
    assert "said 4 times in 3 sessions · last Mar 9" in html
    assert "view=session&amp;id=s2&amp;step=3" in html
    assert "Teach the agent" in html and "Dismiss" in html
    assert (
        "Things you told the agent more than once. Teach one and the agent hears it before it acts."
        in html
    )
    assert "unconfirmed" not in html and "You said" not in html


def test_the_top_section_counts_dismissed_rules(shown):
    assert '<span class="mu">2 dismissed</span>' in shown["html"]


def test_without_confirmed_rules_the_top_section_is_omitted_entirely(shown):
    assert shown["topWithoutConfirmed"] == ["", True]
    assert shown["empty"] == ["", True, ""] and shown["missing"] == ["", ""]


def test_unconfirmed_groups_wait_in_a_fold_as_quotes_with_the_way_to_confirm(shown):
    html = shown["guess"]
    assert "Possible rules — not confirmed yet (1)" in html
    assert "You said: “use pnpm”" in html
    assert "Run /symbiont summarize to confirm which of these are rules." in html
    assert "view=session&amp;id=s2&amp;step=3" in html
    assert "said 4 times in 3 sessions" in html
    assert "3 dismissed" in html


def test_the_fold_draws_nothing_inside_until_opened_and_quotes_are_capped_at_140(shown):
    assert "rrow" not in shown["closed"]
    said = re.search(r'<b class="said">(.*?)</b>', shown["long"]).group(1)
    assert said == "You said: “" + "x" * 139 + "…”"


def test_teach_opens_prefilled_with_the_area_or_the_whole_repo_and_the_rule_text(shown):
    repo, area, guess = shown["drafts"]
    assert (area["when"], area["what"]) == ("web/", "Use pnpm, not npm.")
    assert (repo["when"], repo["what"]) == ("anywhere in this repo", "Use pnpm, not npm.")
    assert (guess["when"], guess["what"]) == ("anywhere in this repo", "use pnpm")


def test_teach_stores_the_lesson_then_marks_the_rule_taught_with_its_lesson_id(shown):
    for posts, key in ((shown["teachPosts"], "rule:s2:3"), (shown["guessTeachPosts"], "rule:g:1")):
        add, triage = posts[:2]
        assert add[0] == "/lessons/add" and add[1]["lessons"][0]["text_in_plain_words"]
        assert triage == [
            "/triage",
            {"project": "my repo", "group_key": key, "taught": True, "lesson_id": "L1"},
        ]
    assert "Taught." in shown["afterTeach"] and "Teach the agent" not in shown["afterTeach"]


def test_dismiss_stores_no_lesson_and_archives_forever_through_triage(shown):
    ((url, body),) = shown["dismissPosts"]
    assert (url, body["group_key"], body["state"], body["return_rule"]) == (
        "/triage", "rule:g:1", "archived", "never",
    )  # fmt: skip
    assert shown["afterDismiss"] == ""


def test_hostile_rule_text_area_and_quotes_are_escaped(shown):
    html = shown["hostile"]
    assert "<img" not in html
    assert "&lt;img src=x onerror=window.__x=1&gt;" in html


def test_after_five_rows_the_rest_fold_behind_show_more(shown):
    assert (shown["foldedRows"], shown["foldedButton"], shown["openRows"]) == (5, True, 7)


def test_the_teach_button_is_a_normal_button_not_a_stretched_block():
    css = (STATIC / "inbox.css").read_text(encoding="utf-8")
    assert ".rrow .gacts{align-self:start;align-items:flex-start" in css
