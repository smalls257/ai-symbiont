"""Plug round 4's single changes on hand-written items and scores."""

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
def r4(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_r4", ROUTEA / "plug_r4.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_r4"] = module
    spec.loader.exec_module(module)
    return module


def lesson(r4, repo, number, error_class="TypeError"):
    from lessons import Lesson

    return Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"{error_class}: boom {number}",
        error_class=error_class,
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def pair(r4):
    right = lesson(r4, "org/r", 1)
    others = tuple(lesson(r4, "org/x", n, "ValueError") for n in range(2, 8))
    situation = f"Ran `{right.failed}` in org/r (file {right.file}). It failed: {right.error}"
    pick = r4.Item(f"{right.lesson_id}-pick", situation, (*others, right), right)
    quiet = r4.Item(f"{right.lesson_id}-silence", situation, others, None)
    return right, others, pick, quiet


def test_rewrite_queries_use_the_rewrite_and_refuse_a_missing_one(r4):
    right, others, pick, _ = pair(r4)
    rewrites = {x.lesson_id: f"Applies when {x.lesson_id}" for x in (right, *others)}
    found = r4.rewrite_queries([pick], rewrites)
    assert all("Applies when" in q["text"] for q in found) and len(found) == 7
    del rewrites[right.lesson_id]
    with pytest.raises(r4.MissingRewriteError):
        r4.rewrite_queries([pick], rewrites)


def test_near_misses_are_confident_wrong_and_missed_right_lessons(r4):
    right, others, pick, quiet = pair(r4)
    scores = {f"{i.item_id}::{x.lesson_id}": 0.1 for i in (pick, quiet) for x in (right, *others)}
    scores[f"{quiet.item_id}::{others[0].lesson_id}"] = 0.8  # confident and wrong
    scores[f"{pick.item_id}::{right.lesson_id}"] = 0.9  # right but under the 0.99 threshold
    answers = sorted(
        row["messages"][2]["content"] for row in r4.near_miss_rows([pick, quiet], scores, 0.99)
    )
    assert answers == ["no", "yes"]


def test_a_night_pairs_each_invented_situation_with_its_lesson_and_one_other(r4):
    right, _, pick, _ = pair(r4)
    invented = {right.lesson_id: ["first moment", "second moment"]}
    extra = [{"messages": []}]
    rows = r4.nightly_rows([pick], invented, extra)
    answers = [row["messages"][2]["content"] for row in rows if row["messages"]]
    assert sorted(answers) == ["no", "no", "yes", "yes"] and len(rows) == 5


def test_operating_point_says_when_nothing_is_safe(r4):
    right, others, pick, quiet = pair(r4)
    wrong = {f"{i.item_id}::{x.lesson_id}": 1.0 for i in (pick, quiet) for x in (right, *others)}
    assert r4.operating_point([pick, quiet], wrong)["status"] == "no safe point"
