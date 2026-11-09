"""The theme x pattern map's comparison rule.

Violation prevented: Paper Tiger. One session of a rare pattern painted every other theme
"less common than usual" in deep blue and the list called it 0%. The pure rule in heatcell.js
runs under node with no DOM.
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
        [node, str(HERE / "heatcell_harness.js"), str(STATIC / "heatcell.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_a_pattern_in_one_of_363_sessions_leaves_every_cell_neutral_as_too_rare(decided):
    cells = decided["rareColumn"]
    assert all(not c["compared"] for c in cells)
    assert {c["reason"] for c in cells} == {"Too rare to compare: 1 session in all"}


def test_a_common_pattern_is_still_compared_by_its_ratio_to_the_usual_rate(decided):
    auth, build, _docs, cli = decided["commonColumn"]
    assert auth["compared"] and auth["ratio"] == pytest.approx((60 / 120) / (100 / 363))
    assert build["compared"] and build["ratio"] < 1
    assert cli["compared"] and cli["ratio"] == pytest.approx((20 / 180) / (100 / 363))


def test_a_theme_expected_to_show_the_pattern_in_under_two_sessions_is_neutral(decided):
    docs = decided["commonColumn"][2]
    assert docs == decided["tinyTheme"]
    assert docs == {"compared": False, "reason": "Too few sessions in docs to compare"}


def test_a_share_that_rounds_to_zero_percent_shows_its_count_instead(decided):
    assert decided["labels"] == ["1 session", "1%", "0%", "14%", "0%"]
