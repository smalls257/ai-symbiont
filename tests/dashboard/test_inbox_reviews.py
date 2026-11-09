"""The Inbox's "What reviewers flagged" section under node, with the real shared triage actions.

Failures guarded against: Paper Tiger (hundreds of single comments as rows), Distributed Monolith
(a second dismiss path) and an unescaped gist reaching the page as markup.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
STATIC = HERE.parents[1] / "src" / "symbiont" / "service" / "static"
HOSTILE = "<img src=x onerror=window.__x=1>"


@pytest.fixture(scope="module")
def shown():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "reviews_harness.js"), str(STATIC)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_repeated_groups_are_rows_with_gist_reviewers_files_fix_and_a_link_to_the_step(shown):
    first = shown["afterClosed"]
    assert first["hidden"] is False
    assert first["title"] == "What reviewers flagged 23 groups 2 dismissed"
    assert "came up 3 times in 2 sessions" in first["rowTexts"][0]
    row = first["rowTexts"][1]
    assert row.startswith("“Possible null dereference”")
    assert "came up 2 times in 2 sessions · CodeRabbit, Copilot · src/a.ts" in row
    assert "fixed by editing a.ts" in row and row.endswith("Dismiss")
    assert ["?project=my%20repo&view=session&id=s1&step=3", ""] in first["links"]


def test_single_comments_wait_in_a_collapsed_fold_that_shows_no_rows(shown):
    first = shown["afterClosed"]
    assert first["summary"] == "Came up in one session (21)"
    assert first["foldOpen"] is False and len(first["rowTexts"]) == 2


def test_an_open_fold_pages_fifteen_then_shows_the_rest(shown):
    assert shown["firstPage"] == {"rows": 17, "more": 1}
    assert shown["secondPage"] == {"rows": 23, "more": 0}


def test_gist_text_stays_text_never_markup(shown):
    first = shown["afterClosed"]
    assert first["tags"] == [] and first["rowTexts"][0].startswith("“" + HOSTILE + "”")
    assert first["hostileRowLabel"] == HOSTILE


def test_dismiss_posts_the_group_key_as_archived_and_the_row_goes(shown):
    gone = shown["dismissed"]
    assert gone["posts"] == [
        [
            "/triage",
            {
                "project": "my repo",
                "group_key": "review:a",
                "state": "archived",
                "return_rule": "never",
            },
        ]
    ]
    assert gone["rows"] == ["review:b"]
    assert gone["title"] == "What reviewers flagged 1 group 1 dismissed"
    assert gone["triage"]["review:a"]["state"] == "archived"
    assert gone["toasts"] == ["Dismissed. It stays counted but is never shown again."]


def test_the_section_hides_when_nothing_is_left_or_nothing_was_found(shown):
    assert shown["emptied"] == {"hidden": True, "children": 0}
    assert shown["preDismissed"] == [True, 0]
    assert shown["none"] == [True, 0] and shown["missing"] == [True, 0]


def test_a_single_comment_alone_has_only_the_fold(shown):
    assert shown["onlySingles"] == {"fold": "Came up in one session (1)", "rows": 0}
