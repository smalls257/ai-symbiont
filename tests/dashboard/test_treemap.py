"""The treemap's folding and label fitting.

Violation prevented: Silent Fallback on the chart. A tile too small for its label, or a file with
no path, used to draw as a blank or half-labeled rectangle that read like missing data. The pure
functions in treemap.js run under node with no DOM; node is a hard requirement, never a skip.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
TREEMAP_JS = HERE.parents[1] / "src" / "symbiont" / "service" / "static" / "treemap.js"
BOX_AREA = 478 * 245
TURNS = {
    "": 36,
    "ledger/statements.py": 10,
    "ledger/test_balance_after_a_very_long_name.py": 8,
    "ledger/summary.py": 8,
    "ledger/refunds.py": 8,
    "ledger/ledger.py": 6,
    "a.py": 2,
    "b.py": 2,
    "c.py": 1,
    "d.py": 1,
    "e.py": 1,
    "f.py": 1,
}


@pytest.fixture(scope="module")
def layout():
    node = shutil.which("node")
    assert node, "node is required for the dashboard tests (the JS gate needs it too)"
    out = subprocess.run(  # noqa: S603
        [node, str(HERE / "treemap_harness.js"), str(TREEMAP_JS)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_every_tile_is_big_enough_and_named(layout):
    min_w, min_h = layout["min"]

    for tile in layout["tiles"]:
        assert tile["name"], tile
        assert tile["w"] >= min_w and tile["h"] >= min_h, tile


def test_small_files_fold_into_one_labeled_tile_with_summed_turns(layout):
    folded = [t for t in layout["tiles"] if t["folded"]]

    assert len(folded) == 1
    other = folded[0]
    assert other["name"] == f"Other files ({len(other['folded'])})"
    assert other["v"] == sum(TURNS[f] for f in other["folded"])
    assert "a.py" in other["title"]


def test_area_stays_proportional_to_turns_after_folding(layout):
    tiles = layout["tiles"]
    total = sum(t["v"] for t in tiles)

    assert total == sum(TURNS.values())
    for tile in tiles:
        assert tile["w"] * tile["h"] == pytest.approx(BOX_AREA * tile["v"] / total, rel=1e-6)


def test_the_file_with_no_path_is_named_not_blank(layout):
    biggest = max(layout["tiles"], key=lambda t: t["v"])

    assert biggest["f"] == "" and biggest["name"] == "No single file"
    assert layout["names"] == ["refunds.py", "No single file", "No single file", "dir"]


def test_nothing_folds_when_everything_fits(layout):
    assert not any(t["folded"] for t in layout["roomy"])
    assert len(layout["roomy"]) == 3
    assert len(layout["single"]) == 1 and layout["none"] == []


def test_names_are_cut_with_an_ellipsis_only_when_they_do_not_fit(layout):
    wide, short, long = layout["fit"]

    assert wide.endswith("…") and len(wide) < len("statements.py")
    assert short == "a.py"
    assert long.endswith("…")


def test_the_other_tile_shrinks_its_font_to_keep_the_count_visible(layout):
    snug, roomy, floor = layout["font"]

    assert 10 <= snug < 13 and roomy == 13 and floor == 10
