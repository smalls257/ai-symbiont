"""Unit tests for the Python gate scripts: nesting, file length, suite floor, claim tags,
result rows. Each gate is tested on the failure it exists to catch and on the near miss
that must stay green."""

import json
from pathlib import Path

import pytest

from gate_loader import load_gate

nesting = load_gate("check_nesting")
length = load_gate("check_file_length")
floor = load_gate("assert_suite_floor")
claims = load_gate("check_claims")
results = load_gate("check_results")

CORE = "src/symbiont/core/x.py"
EDGE = "src/symbiont/store/x.py"

THREE_DEEP = (
    "def f(xs):\n    for x in xs:\n        if x:\n            with x:\n                return x\n"
)
FOUR_DEEP = THREE_DEEP.replace("return x", "if x:\n                    return x")


# --- nesting: God Method ---------------------------------------------------------------


def test_three_deep_passes_and_four_deep_fails():
    assert nesting.offenders(THREE_DEEP, CORE, set()) == []
    assert len(nesting.offenders(FOUR_DEEP, CORE, set())) == 1


def test_the_nesting_limit_is_three_everywhere():
    assert len(nesting.offenders(FOUR_DEEP, EDGE, set())) == 1


def test_an_elif_chain_is_one_level_not_a_staircase():
    source = (
        "def f(x):\n    for i in x:\n        if i == 1:\n            pass\n"
        "        elif i == 2:\n            pass\n        elif i == 3:\n            pass\n"
        "        elif i == 4:\n            pass\n"
    )
    assert nesting.offenders(source, CORE, set()) == []


def test_inner_function_nesting_is_not_charged_to_the_outer_one():
    source = "def outer():\n    def inner(xs):\n" + "\n".join(
        "        " + line for line in FOUR_DEEP.splitlines()[1:]
    )
    found = nesting.offenders(source, CORE, set())
    assert [f.split(":")[2].split()[0] for f in found] == ["inner"]


def test_whitelist_waives_one_function_in_one_file():
    assert nesting.offenders(FOUR_DEEP, CORE, {f"{CORE}:f"}) == []
    assert len(nesting.offenders(FOUR_DEEP, CORE, {"src/symbiont/core/other.py:f"})) == 1


def test_empty_whitelist_file_is_a_gate_error(tmp_path):
    empty = tmp_path / "wl.txt"
    empty.write_text("")
    with pytest.raises(nesting.GateConfigError):
        nesting.read_whitelist(empty)


# --- file length: God Class ------------------------------------------------------------


def test_file_length_limits_follow_the_tier():
    assert length.limit_for("src/symbiont/core/a.py") == 400
    assert length.limit_for("src/symbiont/store/a.py") == 400
    assert length.limit_for("tests/a.py") == 600
    assert length.limit_for("scripts/a.py") == 400
    assert length.limit_for("ops/a.py") == 400
    assert length.limit_for("docs/a.py") is None


def test_long_source_file_fails_unless_whitelisted_and_warns_above_300():
    text = "x = 1\n" * 401
    assert length.too_long("src/symbiont/core/a.py", text, set()) is not None
    assert length.too_long("src/symbiont/core/a.py", text, {"src/symbiont/core/a.py"}) is None
    assert length.too_long("src/symbiont/core/a.py", "x = 1\n" * 400, set()) is None
    assert length.long_but_allowed("src/symbiont/core/a.py", "x = 1\n" * 350) is not None
    assert length.long_but_allowed("src/symbiont/core/a.py", "x = 1\n" * 300) is None


def _class_source(methods: int, body_lines: int = 0) -> str:
    defs = "".join(f"    def m{i}(self): ...\n" for i in range(methods))
    return "class Big:\n" + defs + "    pass\n" * body_lines


def test_class_with_more_than_twelve_public_methods_fails_private_ones_do_not_count():
    path = "src/symbiont/core/a.py"
    assert length.oversized_classes(path, _class_source(12), set()) == []
    assert len(length.oversized_classes(path, _class_source(13), set())) == 1
    private = _class_source(0).replace("class Big:\n", "class Big:\n") + "".join(
        f"    def _p{i}(self): ...\n" for i in range(20)
    )
    assert length.oversized_classes(path, private, set()) == []


def test_class_over_200_lines_fails_and_whitelist_waives_it():
    path = "src/symbiont/core/a.py"
    assert len(length.oversized_classes(path, _class_source(1, body_lines=200), set())) == 1
    assert length.oversized_classes(path, _class_source(1, 200), {f"{path}:Big"}) == []


# --- suite floor: Paper Tiger ----------------------------------------------------------


def _junit(tmp_path: Path, tests: int, skipped: int = 0, failures: int = 0) -> Path:
    report = tmp_path / "junit.xml"
    report.write_text(
        f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" failures="{failures}" '
        f'errors="0"/></testsuites>'
    )
    return report


def test_a_suite_that_collected_nothing_is_not_green(tmp_path):
    counts = floor.read_counts(_junit(tmp_path, tests=0))
    assert floor.violations(counts, floor=240)


def test_any_skip_fails_with_no_waiver(tmp_path):
    counts = floor.read_counts(_junit(tmp_path, tests=300, skipped=1))
    assert any("skipped" in v for v in floor.violations(counts, floor=240))


def test_floor_met_with_no_skips_is_green(tmp_path):
    assert floor.violations(floor.read_counts(_junit(tmp_path, tests=300)), floor=240) == []


def test_missing_report_means_the_suite_did_not_run(tmp_path):
    with pytest.raises(floor.FloorGateError):
        floor.read_counts(tmp_path / "absent.xml")


def test_floor_ratchets_up_never_down():
    counts = floor.SuiteCounts(tests=400, skipped=0, failed=0)
    assert floor.ratcheted_floor(counts, 240) == 380
    assert floor.ratcheted_floor(floor.SuiteCounts(100, 0, 0), 240) == 240


def test_committed_floor_file_is_readable():
    assert floor.read_floor() >= 240


# --- claim tags: Paper Tiger -----------------------------------------------------------


def test_untagged_quantity_fails_and_tagged_passes():
    bad = claims.problems_in("docs/a.md", "The learner is 3x faster.\n")
    ok = claims.problems_in("docs/a.md", "The learner is 3x faster [measured].\n")
    assert len(bad) == 1 and ok == []


def test_tag_in_a_table_row_covers_the_row():
    table = "| arm | AUROC |\n| fly | 0.81 s [hypothesis] |\n"
    assert claims.problems_in("docs/a.md", table) == []


def test_html_span_tag_counts_and_html_tr_is_one_unit():
    html = (
        '<table><tr>\n<td>cost 4 tokens</td>\n<td><span class="t m">m</span></td>\n</tr></table>\n'
    )
    assert claims.problems_in("docs/a.html", html) == []
    assert claims.problems_in("docs/a.html", "<p>about 40%</p>\n") != []


def test_code_fences_and_plain_words_are_not_claims():
    text = "```\nelapsed 5 s\n```\nWe ran 2026-10-27 sessions and tasks.\n"
    assert claims.problems_in("docs/a.md", text) == []


def test_forbidden_phrases_and_bare_doom():
    assert claims.problems_in("docs/a.md", "It learns in seconds.\n")
    assert claims.problems_in("docs/a.md", "The agent plays Doom.\n")
    assert claims.problems_in("docs/a.md", "It plays Freedoom via ViZDoom, not Doom.\n") == []


def test_scope_is_docs_results_readme_prereg():
    assert claims.in_scope("docs/x/y.md") and claims.in_scope("prereg/p.md")
    assert claims.in_scope("README.md") and claims.in_scope("results/a.md")
    assert not claims.in_scope("CLAUDE.md") and not claims.in_scope("src/a.py")
    assert not claims.in_scope("results/a.json")
    assert not claims.in_scope("docs/standards/quality-gates.html")


# --- result rows: Silent Fallback by omission ------------------------------------------


def _doc(*rows: dict) -> dict:
    return {"rows": list(rows)}


def test_row_without_a_valid_role_fails():
    found = results.problems_in("r.json", _doc({"arm": "plain", "role": "winner"}))
    assert len(found) == 1


def test_dashboard_spelling_of_under_test_is_accepted():
    assert results.problems_in("r.json", _doc({"arm": "x", "role": "under test"})) == []


def test_fly_row_needs_a_counters_row_on_the_same_split():
    fly = {"arm": "fly", "role": "under_test", "split": "test"}
    counters = {"arm": "counters", "role": "reference", "split": "test"}
    assert results.problems_in("r.json", _doc(fly)) != []
    assert results.problems_in("r.json", _doc(fly, {**counters, "split": "train"})) != []
    assert results.problems_in("r.json", _doc(fly, counters)) == []


def test_files_without_a_rows_list_are_not_scoreboards():
    assert results.problems_in("calibration.json", {"pool": [1, 2]}) == []


def test_every_committed_result_file_passes():
    root = Path(__file__).resolve().parents[2]
    for path in sorted((root / "results").glob("*.json")):
        assert results.problems_in(path.name, json.loads(path.read_text())) == []
