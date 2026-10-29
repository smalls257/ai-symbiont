"""Plug split checks, confabulation, abstention and ranked choice, on hand-written lessons."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}


@pytest.fixture(autouse=True)
def forget_script_modules():
    """Drop only modules loaded from scripts/; shared libraries stay loaded."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


@pytest.fixture
def plug(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug", ROUTEA / "plug.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug"] = module
    spec.loader.exec_module(module)
    return module


def lesson(plug, repo, lesson_id, error="TypeError", added=("--flag",), fix="pytest --flag"):
    return plug.Lesson(
        lesson_id=lesson_id,
        repo=repo,
        program="pytest",
        file="tests/test_a.py",
        failed="pytest",
        error=f"{error}: boom",
        error_class=error,
        fix=fix,
        added=added,
    )


def repo_of(plug, repo, count, prefix):
    return [lesson(plug, repo, f"{prefix}{n:03d}", added=(f"--{prefix}{n}",)) for n in range(count)]


def test_split_names_scored_and_meta_repos_and_pairs_controls_by_name(plug):
    by_repo = {
        "org/big1": repo_of(plug, "org/big1", 10, "a"),
        "org/big2": repo_of(plug, "org/big2", 12, "b"),
        "org/small": repo_of(plug, "org/small", 3, "c"),
        "org/single": repo_of(plug, "org/single", 1, "d"),
        "Azure/msrest-for-python": repo_of(plug, "Azure/msrest-for-python", 13, "e"),
    }
    split = plug.plan_split(by_repo, habit_repos=["aidev/repo"])
    assert sorted(split.test) == ["org/big1", "org/big2"]
    assert sorted(split.meta) == ["org/small"]
    assert split.control_of == {"org/big1": "org/big2", "org/big2": "org/big1"}


def test_split_refuses_a_shared_repo_or_lesson_id(plug):
    test = {"org/big": repo_of(plug, "org/big", 10, "a")}
    meta = {"org/small": [lesson(plug, "org/small", "a000", added=("--x",))]}
    with pytest.raises(plug.SharedSplitError, match="lesson ids"):
        plug.check_unseen(plug.Split(test, meta, {}), habit_repos=[])
    with pytest.raises(plug.SharedSplitError, match="habit rows and scored"):
        plug.check_unseen(plug.Split(test, {}, {}), habit_repos=["org/big"])


def test_shared_failure_keys_are_counted_not_refused(plug):
    test = {"org/big": [lesson(plug, "org/big", "t1", added=("--same",))]}
    meta = {"org/small": [lesson(plug, "org/small", "m1", added=("--same",))]}
    split = plug.Split(test, meta, {})
    plug.check_unseen(split, habit_repos=[])
    assert plug.shared_keys(split) == ["t1"]


def test_confabulation_hit_near_miss_and_shared_key(plug):
    own = [lesson(plug, "org/r", "r1", error="KeyError", added=("--own",), fix="run --own")]
    wrong = [lesson(plug, "org/w", "w1", added=("--alpha", "--beta"), fix="tox --alpha --beta")]
    assert plug.confabulates("Run it with `--alpha` and --beta.", own, wrong)
    assert plug.confabulates("Use tox --alpha --beta", own, wrong)
    assert not plug.confabulates("Run it with --alpha only.", own, wrong)
    shared = [lesson(plug, "org/w", "w2", error="KeyError", added=("--own",), fix="run --own")]
    assert not plug.confabulates("run --own", own, shared)


def test_confabulation_refuses_a_lesson_without_fix_tokens(plug):
    with pytest.raises(ValueError):
        plug.confabulates("anything", [], [lesson(plug, "org/w", "w1", added=())])


@pytest.mark.parametrize(
    ("answer", "abstains"),
    [
        ("No lesson I hold covers that.", True),
        ("I have no lesson about that command.", True),
        ("NO LESSON matches.", True),
        ("Run pytest --flag.", False),
    ],
)
def test_abstention_forms(plug, answer, abstains):
    assert plug.abstains(answer) is abstains


def test_ranked_hit_needs_a_strict_first_place(plug):
    assert plug.ranked_hit("tests", {"tests": -1.0, "naming": -2.0})
    assert not plug.ranked_hit("tests", {"tests": -2.0, "naming": -1.0})
    assert not plug.ranked_hit("tests", {"tests": -1.0, "naming": -1.0})
