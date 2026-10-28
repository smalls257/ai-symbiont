"""Strata labels and the two screen rules: pure functions, synthetic pools."""

import sys
from pathlib import Path

import pytest

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"


@pytest.fixture(autouse=True)
def calibration_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(CALIBRATION))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def diff(*paths):
    return "".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n" for p in paths)


def test_single_area_patches_get_that_area(calibration_on_path):
    from strata import subsystem_of

    assert subsystem_of(diff("sqlglot/dialects/duckdb.py")) == "dialects"
    assert subsystem_of(diff("sqlglot/parser.py")) == "parser"
    assert subsystem_of(diff("sqlglot/tokens.py")) == "parser"
    assert subsystem_of(diff("sqlglot/optimizer/qualify.py")) == "optimizer"
    assert subsystem_of(diff("sqlglot/executor/python.py")) == "executor"
    assert subsystem_of(diff("sqlglot/generator.py")) == "generator"
    assert subsystem_of(diff("sqlglot/helper.py")) == "other"


def test_expressions_alone_is_expressions_but_is_ignored_beside_another_area():
    from strata import subsystem_of

    assert subsystem_of(diff("sqlglot/expressions.py")) == "expressions"
    assert subsystem_of(diff("sqlglot/expressions.py", "sqlglot/dialects/mysql.py")) == "dialects"


def test_two_non_expression_areas_are_multi():
    from strata import subsystem_of

    assert subsystem_of(diff("sqlglot/parser.py", "sqlglot/generator.py")) == "multi"
    assert subsystem_of(diff("sqlglot/dialects/a.py", "sqlglot/dialects/b.py")) == "dialects"
    assert subsystem_of(diff("sqlglot/parser.py", "sqlglot/helper.py")) == "multi"
    assert subsystem_of("") == "other"


def test_size_band_edges():
    from strata import size_band

    assert [size_band(n) for n in (0, 9, 10, 29, 30, 59)] == ["S", "S", "M", "M", "L", "L"]


def test_label_pool_adds_both_fields_from_the_rows_patches():
    from label_pool import label_pool

    pool = [{"instance_id": "a", "gold_changed_lines": 12}]
    labeled = label_pool(pool, {"a": diff("sqlglot/parser.py")})
    assert labeled == [pool[0] | {"subsystem": "parser", "size_band": "M"}]
    with pytest.raises(KeyError):
        label_pool(pool, {})


def entry(iid, subsystem="dialects", band="S", lines=1):
    return {
        "instance_id": iid,
        "gold_changed_lines": lines,
        "subsystem": subsystem,
        "size_band": band,
    }


def wide_pool():
    cells = [("dialects", "S", 30), ("parser", "M", 20), ("optimizer", "L", 3), ("multi", "M", 1)]
    return [
        entry(f"{sub}-{band}-{n:02d}", sub, band)
        for sub, band, count in cells
        for n in range(count)
    ]


def test_stratified_is_deterministic_and_has_n_unique_ids():
    from screen_rules import stratified_screen

    first = stratified_screen(wide_pool(), set(), seed=1)
    assert first == stratified_screen(list(reversed(wide_pool())), set(), seed=1)
    assert len(first) == len(set(first)) == 40
    assert first != stratified_screen(wide_pool(), set(), seed=2)


def test_stratified_skips_excluded_ids():
    from screen_rules import stratified_screen

    pool = wide_pool()
    banned = {item["instance_id"] for item in pool if item["subsystem"] == "parser"}
    picked = stratified_screen(pool, banned, seed=1)
    assert not banned & set(picked) and len(picked) == 34, "30 + 3 + 1 left"


def test_round_robin_gives_small_cells_everything_and_big_cells_the_rest():
    from screen_rules import pick_counts, stratified_screen

    pool = wide_pool()
    picked = stratified_screen(pool, set(), seed=1)
    counts = pick_counts(pool, picked)
    assert counts["multi/M"] == 1 and counts["optimizer/L"] == 3
    assert counts["dialects/S"] + counts["parser/M"] == 36
    assert abs(counts["dialects/S"] - counts["parser/M"]) <= 1
    assert sum(counts.values()) == 40


def test_the_first_ten_picks_already_span_every_cell():
    from screen_rules import pick_counts, stratified_screen

    pool = wide_pool()
    assert len(pick_counts(pool, stratified_screen(pool, set(), seed=1)[:10])) == 4


def test_a_pool_smaller_than_n_returns_all_of_it():
    from screen_rules import stratified_screen

    pool = [entry(f"t{n}") for n in range(5)]
    assert sorted(stratified_screen(pool, {"t0"}, seed=1)) == ["t1", "t2", "t3", "t4"]


def test_unlabeled_pool_entry_raises_naming_the_task():
    from screen_rules import UnlabeledPoolError, stratified_screen

    with pytest.raises(UnlabeledPoolError, match="old-task"):
        stratified_screen([{"instance_id": "old-task", "gold_changed_lines": 1}], set())


def test_smallest_rule_is_the_original_smallest_forty_and_ignores_exclusions():
    from screen_rules import ScreenRule, select_screen

    pool = [{"instance_id": f"t{n:02d}", "gold_changed_lines": 50 - n // 2} for n in range(60)]
    expected = [
        p["instance_id"]
        for p in sorted(pool, key=lambda i: (i["gold_changed_lines"], i["instance_id"]))[:40]
    ]
    assert select_screen(ScreenRule.SMALLEST, pool, {"t59"}) == expected
