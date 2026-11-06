"""The Add context list's collapsible sections.

Violation prevented: Paper Tiger. A long list grouped by kind that can only be scrolled shows every
pain point and fails "let me work through one kind at a time". The pure storage and markup functions
in painlist.js run under node with no DOM; node is a hard requirement here as for the JS gate.
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
        [node, str(HERE / "painlist_harness.js"), str(STATIC / "painlist.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return json.loads(out.stdout)


def test_the_state_lives_under_a_per_repository_key_and_only_that_repository_reads_it(decided):
    assert decided["key"] == "symbiont.plist.collapsed.demo"
    assert decided["stored"] == ["repeat"]
    assert decided["otherProject"] == []
    assert decided["missing"] == []


def test_saving_writes_the_collapsed_kind_ids_as_a_json_array(decided):
    assert json.loads(decided["saved"]["symbiont.plist.collapsed.demo"]) == ["repeat", "tdd"]


def test_an_unreadable_value_opens_everything_and_warns_naming_the_key(decided):
    assert decided["corrupt"] == [] and decided["wrongShape"] == []
    warned = [w for w in decided["warnings"] if "could not read symbiont.plist.collapsed.demo" in w]
    assert len(warned) == 2


def test_a_refused_save_is_a_visible_warning_not_a_silent_loss(decided):
    assert any("could not save symbiont.plist.collapsed.demo" in w for w in decided["warnings"])


def test_an_open_section_is_a_disclosure_button_with_the_count_and_a_visible_list(decided):
    html = decided["openHtml"]

    assert 'aria-expanded="true" aria-controls="plist-repeat"' in html
    assert "Repeated failure · 14" in html
    assert (
        '<div class="items" id="plist-repeat" role="listbox" aria-labelledby="plist-h-repeat">'
        in html
    )


def test_a_collapsed_section_hides_its_items_and_keeps_its_heading(decided):
    html = decided["closedHtml"]

    assert 'aria-expanded="false" aria-controls="plist-repeat"' in html
    assert (
        '<div class="items" id="plist-repeat" role="listbox" '
        'aria-labelledby="plist-h-repeat" hidden>' in html
    )
    assert 'aria-expanded="true" aria-controls="plist-tdd"' in html


def test_labels_from_data_are_escaped(decided):
    assert "<b>x</b>" not in decided["openHtml"] and "&lt;b&gt;x&lt;/b&gt;" in decided["openHtml"]


def test_the_page_loads_the_list_module_before_the_dashboard_script_and_expands_on_selection():
    page = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    script = (STATIC / "dashboard.js").read_text(encoding="utf-8")

    assert page.index("/dashboard/painlist.js") < page.index("/dashboard/dashboard.js")
    selected = script[script.index("function selectPain(") :]
    assert selected.startswith(
        "function selectPain(id){setGroupOpen(byId(id).kind,true);showPain(id);}"
    )
    assert "renderDashboard();renderList();showPain(1);" in script


def test_a_toggle_returns_focus_to_its_heading_after_the_list_is_redrawn():
    script = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    toggle = script[script.index("function toggleGroup(") : script.index("function itemHtml(")]

    assert toggle.index("renderList()") < toggle.index(".focus()")
    assert "b.onclick=()=>toggleGroup(" in script
