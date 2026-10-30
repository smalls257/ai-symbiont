"""Core D2 test selection: hash order is fixed, never-solved tasks drop, untried tasks stay."""

import importlib.util
from pathlib import Path

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
spec = importlib.util.spec_from_file_location(
    "core2_select_tests", ROUTEB / "core2_select_tests.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_tried_and_never_solved_drops_but_untried_stays():
    merged = module.merge_solves([{"a": [3, 0], "b": [2, 1]}, {"a": [1, 0], "c": [1, 1]}])
    assert merged["a"] == [4, 0]
    assert module.never_solved(merged) == {"a"}
    picked = module.select(["a", "b", "c", "d"], merged, 10)
    assert "a" not in picked["test"] and "d" in picked["test"]
    assert picked["dropped_never_solved"] == 1 and picked["with_existing_data"] == 3


def test_order_is_the_sha256_of_the_prefixed_id_and_size_caps_it():
    ids = [f"t{i}" for i in range(20)]
    picked = module.select(ids, {}, 5)
    assert picked["test"] == sorted(ids, key=module.hash_key)[:5]
    assert picked["not_taken"] == 15
