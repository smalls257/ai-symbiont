"""Every lesson kind the snapshot sends has a label and color in the page, or it fails to draw."""

import re
from pathlib import Path

from symbiont.service.dashboard_view import KIND_OF_SIGNAL

DASHBOARD_JS = Path(__file__).parents[2] / "src/symbiont/service/static/dashboard.js"


def test_every_snapshot_kind_has_a_label_and_color_in_the_page():
    table = re.search(r"const KINDS=\{(.*?)\n\};", DASHBOARD_JS.read_text(), re.S)
    assert table is not None
    drawn = set(re.findall(r"^\s*(\w+):\{label:", table.group(1), re.M))
    assert set(KIND_OF_SIGNAL.values()) <= drawn
