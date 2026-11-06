"""The Ignored group of the Add context list.

Violation prevented: Silent Fallback. A pattern the developer set aside must stay findable and
undoable: listed, collapsed until opened, escaped, with a Restore button each. The pure functions
in ignored.js run under node with no DOM.
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
        [
            node,
            str(HERE / "ignored_harness.js"),
            str(STATIC / "ignored.js"),
            str(STATIC / "painlist.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_the_group_is_collapsed_until_the_developer_opens_it_and_remembers_per_repository(decided):
    assert decided["key"] == "symbiont.ignored.open.demo"
    assert decided["defaultOpen"] is False and decided["afterOpening"] is True


def test_an_unreadable_store_is_warned_about_naming_the_key_not_swallowed(decided):
    assert decided["brokenOpen"] is False
    assert any("symbiont.ignored.open.demo" in w for w in decided["warnings"])


def test_each_entry_shows_its_escaped_label_with_a_restore_button(decided):
    assert "&lt;img" in decided["html"] and "<img" not in decided["html"]
    assert 'data-restore="0"' in decided["html"] and "Restore" in decided["html"]
    assert decided["group"]["kind"] == "ignored" and decided["group"]["count"] == 1
    assert decided["group"]["role"] == "list"
    assert "Nothing is ignored" in decided["empty"]


def test_the_empty_state_draws_the_ignored_list_with_restore_when_patterns_are_ignored(decided):
    """Failure guarded against: every lesson ignored, the only Restore control never drawn."""
    html = decided["emptyState"]
    assert 'data-kind="ignored"' in html and 'aria-expanded="true"' in html
    assert 'data-restore="0"' in html and "&lt;img" in html and "<img" not in html
    assert " hidden>" not in html


def test_the_empty_state_draws_nothing_when_nothing_is_ignored(decided):
    assert decided["emptyStateNothingIgnored"] == ""
