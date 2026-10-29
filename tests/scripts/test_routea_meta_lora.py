"""METALORA: repo domains hold out cleanly, Reptile's outer rule and the test cells are pinned."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def lessons_for(lessons_mod, repo, count, offset=0):
    return [
        lessons_mod.Lesson(
            lesson_id=f"{repo}-{offset + i:03d}",
            repo=repo,
            program="pytest",
            file=f"tests/test_{i}.py",
            failed=f"pytest tests/test_{i}.py",
            error="ModuleNotFoundError: No module named 'x'",
            error_class="ModuleNotFoundError",
            fix=f"PYTHONPATH=src{i} pytest tests/test_{i}.py",
            added=(f"PYTHONPATH=src{i}",),
        )
        for i in range(count)
    ]


def pool(lessons_mod, big=12, small=4, tiny=2):
    """12 repos big enough to hold out, 3 meta-training repos and one too small to use."""
    found = []
    for index in range(big):
        found += lessons_for(lessons_mod, f"org/big{index}", 10 + index % 3)
    for index in range(small):
        found += lessons_for(lessons_mod, f"org/small{index}", 3 + index)
    found += lessons_for(lessons_mod, "org/tiny", tiny)
    return found


def test_held_out_repos_never_reach_meta_training(monkeypatch):
    lessons_mod = load(monkeypatch, "lessons")
    domains = load(monkeypatch, "meta_domains")
    split = domains.split_domains(pool(lessons_mod))
    assert len(split.test) == len(split.val) == domains.HELD_OUT_REPOS
    assert not (set(split.test) | set(split.val)) & set(split.train)
    # the two big repos left over train; the tiny repo (2 lessons) makes no inner loop
    assert "org/tiny" not in split.train
    assert sum(name.startswith("org/big") for name in split.train) == 2
    assert all(len(ids) >= domains.MIN_HELD_OUT_LESSONS for ids in split.test.values())


def test_the_split_follows_the_repo_name_not_the_input_order(monkeypatch):
    lessons_mod = load(monkeypatch, "lessons")
    domains = load(monkeypatch, "meta_domains")
    lessons = pool(lessons_mod)
    assert domains.split_domains(lessons) == domains.split_domains(list(reversed(lessons)))


def test_a_leaked_lesson_or_repo_raises_rather_than_being_dropped(monkeypatch):
    domains = load(monkeypatch, "meta_domains")
    leaked_lesson = domains.Split(train={"a": ["x", "y"]}, val={"b": ["y"]}, test={})
    with pytest.raises(domains.HoldOutLeakError):
        domains.check_held_out(leaked_lesson)
    leaked_repo = domains.Split(train={"a": ["x"]}, val={}, test={"a": ["z"]})
    with pytest.raises(domains.HoldOutLeakError):
        domains.check_held_out(leaked_repo)


def test_too_few_large_repos_refuses_to_split(monkeypatch):
    lessons_mod = load(monkeypatch, "lessons")
    domains = load(monkeypatch, "meta_domains")
    with pytest.raises(ValueError, match="need 10"):
        domains.split_domains(pool(lessons_mod, big=9))


def test_one_lesson_per_repo_error_and_fix(monkeypatch):
    lessons_mod = load(monkeypatch, "lessons")
    domains = load(monkeypatch, "meta_domains")
    twice = lessons_for(lessons_mod, "org/a", 3) + lessons_for(lessons_mod, "org/a", 3, offset=50)
    assert [lesson.lesson_id for lesson in domains.distinct_lessons(twice)] == [
        "org/a-000",
        "org/a-001",
        "org/a-002",
    ]


def test_reptile_moves_the_start_part_way_and_anneals_to_zero(monkeypatch):
    recipe = load(monkeypatch, "meta_recipe")
    start, adapted = np.array([0.0, 2.0]), np.array([1.0, 0.0])
    assert recipe.interpolate(start, adapted, 0.25).tolist() == [0.25, 1.5]
    assert recipe.outer_step(0, 100, 1.0) == 1.0
    assert recipe.outer_step(50, 100, 1.0) == pytest.approx(0.5)
    assert recipe.outer_step(99, 100, 0.3) == pytest.approx(0.003)
    with pytest.raises(ValueError):
        recipe.outer_step(100, 100, 1.0)


def test_every_meta_training_repo_is_visited_equally(monkeypatch):
    recipe = load(monkeypatch, "meta_recipe")
    order = recipe.domain_order(["a", "b", "c"], 9, seed=0)
    assert sorted(order) == ["a"] * 3 + ["b"] * 3 + ["c"] * 3
    assert order == recipe.domain_order(["a", "b", "c"], 9, seed=0)


def test_cells_run_short_budgets_then_lcaps_full_budget(monkeypatch):
    recipe = load(monkeypatch, "meta_recipe")
    assert recipe.full_budget(10) == 120  # LCAP's one-10 run: 60 rows x 8 epochs / batch 4
    assert recipe.cells([3, 10]) == [
        (3, 0),
        (3, 8),
        (3, 15),
        (3, 30),
        (3, 36),
        (10, 0),
        (10, 8),
        (10, 15),
        (10, 30),
        (10, 120),
    ]
    assert recipe.taught(["a", "b", "c"], 2) == ["a", "b"]
    with pytest.raises(ValueError):
        recipe.taught(["a"], 3)


def test_reaches_names_the_fewest_updates_that_match_blanks_full_budget(monkeypatch):
    score_meta = load(monkeypatch, "score_meta")

    def row(arm, iters, recall):
        return {
            "question_set": "template",
            "arm": arm,
            "lessons": 3,
            "iters": iters,
            "recall": recall,
        }

    rows = [row("blank", 36, 0.5), row("meta", 8, 0.2), row("meta", 15, 0.5), row("meta", 36, 0.4)]
    assert score_meta.reaches(rows, "meta", "template") == [
        {"lessons": 3, "blank_full_budget_recall": 0.5, "fewest_iters_to_match": 15}
    ]
    never = [row("blank", 36, 0.9), row("meta", 15, 0.5)]
    assert score_meta.reaches(never, "meta", "template")[0]["fewest_iters_to_match"] is None
