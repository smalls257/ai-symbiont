"""The Inbox's "Rules you've stated" section under node, with the real shared triage actions.

Failures guarded against: Distributed Monolith (a second Teach or archive path), Leaky Narrative
(an unconfirmed rule that reads as a fact), and an unescaped rule or quote reaching innerHTML.
"""

import json
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


def test_a_row_says_the_rule_how_often_and_when_and_links_each_quote_to_its_step(shown):
    html = shown["html"]
    assert "<b>Use pnpm, not npm.</b>" in html
    assert "said 4 times in 3 sessions · last Mar 9" in html
    assert "view=session&amp;id=s2&amp;step=3" in html
    assert "Teach the agent" in html and "Dismiss" in html
    assert (
        "Things you told the agent more than once. Teach one and the agent hears it before it acts."
        in html
    )
    assert "unconfirmed" not in html


def test_an_unconfirmed_rule_says_it_was_only_grouped_by_shared_words(shown):
    assert (
        "unconfirmed — grouped by shared words; run /symbiont summarize to confirm"
        in shown["guess"]
    )


def test_teach_opens_prefilled_with_the_area_or_the_whole_repo_and_the_rule_text(shown):
    repo, area = shown["drafts"]
    assert (area["when"], area["what"]) == ("web/", "Use pnpm, not npm.")
    assert (repo["when"], repo["what"]) == ("anywhere in this repo", "Use pnpm, not npm.")


def test_teach_stores_the_lesson_then_marks_the_rule_taught_with_its_lesson_id(shown):
    (add, triage) = shown["teachPosts"][:2]
    assert add[0] == "/lessons/add" and add[1]["lessons"][0]["text_in_plain_words"]
    assert triage == [
        "/triage",
        {"project": "my repo", "group_key": "rule:s2:3", "taught": True, "lesson_id": "L1"},
    ]
    assert "Taught." in shown["afterTeach"] and "Teach the agent" not in shown["afterTeach"]


def test_no_lesson_is_stored_before_the_teach_click(shown):
    assert [p[0] for p in shown["dismissPosts"]] == ["/triage"]


def test_dismiss_archives_the_rule_forever_through_triage_and_hides_it(shown):
    ((url, body),) = shown["dismissPosts"]
    assert (url, body["group_key"], body["state"], body["return_rule"]) == (
        "/triage", "rule:g:1", "archived", "never",
    )  # fmt: skip
    assert "rrow" not in shown["afterDismiss"]
    assert "No repeated rules were found yet." in shown["afterDismiss"]


def test_hostile_rule_text_area_and_quotes_are_escaped(shown):
    html = shown["hostile"]
    assert "<img" not in html and "onerror=window" not in html.replace("&lt;img src=x onerror", "")
    assert "&lt;img src=x onerror=window.__x=1&gt;" in html


def test_after_five_rows_the_rest_fold_behind_show_more(shown):
    assert (shown["foldedRows"], shown["foldedButton"], shown["openRows"]) == (5, True, 7)


def test_with_no_rules_one_line_says_none_were_found_yet(shown):
    for html in (shown["empty"], shown["missing"]):
        assert "No repeated rules were found yet." in html and "rrow" not in html
