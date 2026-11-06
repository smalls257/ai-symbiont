"""The timeline's row folding and label wrapping.

Violation prevented: Leaky Narrative on the chart. A label running across the plot or a dozen
rows crammed into one panel made the demo unreadable; the pure layout functions in timeline.js
run under node with no DOM. Node is a hard requirement here as for the JS gate, never a skip.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
TIMELINE_JS = HERE.parents[1] / "src" / "symbiont" / "service" / "static" / "timeline.js"


@pytest.fixture(scope="module")
def layout():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "timeline_harness.js"), str(TIMELINE_JS)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_at_most_five_rows_then_one_row_for_the_rest(layout):
    rows = layout["rows"]

    assert [r["title"] for r in rows[:5]] == ["m0", "m1", "m2", "m3", "m4"]
    assert rows[5]["title"] == "Other repeated mistakes (3 more)" and rows[5]["folded"] == 3
    assert len(rows) == 6


def test_the_folded_row_holds_the_union_of_the_folded_sessions(layout):
    folded = layout["rows"][5]["s"]

    assert folded == sorted(set(folded))
    assert folded == [0, 1, 3, 4, 6, 7, 10]


def test_a_mistake_seen_once_is_not_repeated_and_few_rows_need_no_fold(layout):
    assert layout["fewRows"] == ["m0", "m1", "m2"]
    assert "only once" not in [r["title"] for r in layout["rows"]]


def test_a_long_label_wraps_to_two_lines_and_ends_in_an_ellipsis(layout):
    assert layout["short"] == ["your edits to `ledger/refunds.py` were", "redone"]
    assert len(layout["long"]) == 2 and layout["long"][1].endswith("…")
    assert all(len(line) <= 40 for line in layout["long"] + layout["path"])
    assert layout["path"][1].endswith("…") and layout["empty"] == [""]


def test_ticks_and_dots_adapt_to_the_number_of_sessions(layout):
    assert layout["ticks"] == [5, 1, 1]
    dense, sparse, single = layout["radii"]
    assert 4 <= dense < sparse == single == 10


def test_the_page_loads_timeline_js_and_carries_the_mark():
    static = TIMELINE_JS.parent
    html = (static / "dashboard.html").read_text(encoding="utf-8")
    page = (static.parent / "dashboard_page.py").read_text(encoding="utf-8")

    assert html.index("timeline.js") < html.index("dashboard.js")
    assert "/dashboard/timeline.js" in page
    assert 'class="mark"' in html and html.index('class="mark"') < html.index("ai-symbiont</div>")
