"""The Held back list on the Pain points stage.

Violation prevented: Paper Tiger. The page used to be sent the failures mining would not teach and
drew none of them. The pure markup functions in heldback.js run under node with no DOM.
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
        [node, str(HERE / "heldback_harness.js"), str(STATIC / "heldback.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_one_is_singular_and_every_other_count_is_plural(decided):
    assert (decided["one"], decided["many"], decided["zero"]) == (
        "1 session",
        "2 sessions",
        "0 times",
    )


def test_each_failure_shows_what_happened_sessions_minutes_and_the_hold_reason(decided):
    html = decided["html"]

    assert "1 session · 9 times · about 18 min · no fix shown" in html
    assert "4 sessions · 1 time · about 2 min" in html
    assert '<span class="cmd">make lint</span> fails' in html


def test_text_from_a_record_is_escaped(decided):
    assert "<img" not in decided["html"]
    assert "&lt;img src=x onerror=1&gt;" in decided["html"]


def test_the_group_is_a_disclosure_group_with_the_listed_count(decided):
    assert (decided["kind"], decided["count"], decided["role"]) == ("heldback", 2, "list")
