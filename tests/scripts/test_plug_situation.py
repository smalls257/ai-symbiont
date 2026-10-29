"""Plug situation items and scoring on hand-written lessons."""

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
def sit(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_situation", ROUTEA / "plug_situation.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_situation"] = module
    spec.loader.exec_module(module)
    return module


def lesson(sit, repo, number, error="TypeError"):
    return sit.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"{error}: boom {number}",
        error_class=error,
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def pool(sit, size=80):
    return [lesson(sit, f"org/other{n % 7}", 100 + n, error="KeyError") for n in range(size)]


def test_items_hold_the_repos_other_lessons_and_never_the_silent_one(sit):
    lessons = [lesson(sit, "org/r", n) for n in range(40)]
    items = sit.build_items({"org/r": lessons}, pool(sit))
    assert len(items) == 40
    assert sum(item.applies is None for item in items) == 10  # every fourth lesson
    for item, source in zip(items, lessons, strict=True):
        shown = {other.lesson_id for other in item.prompt_lessons}
        assert len(item.prompt_lessons) == sit.PROMPT_LESSONS
        assert {other.lesson_id for other in lessons if other is not source} <= shown
        assert (source.lesson_id in shown) is (item.applies is not None)


def test_too_few_lessons_to_fill_the_prompt_raises(sit):
    with pytest.raises(ValueError, match="cannot fill"):
        sit.build_items({"org/r": [lesson(sit, "org/r", 1)]}, pool(sit, size=10))


def test_verdicts_pick_useful_wrong_and_silent(sit):
    right, other = lesson(sit, "org/r", 1), lesson(sit, "org/x", 2, error="KeyError")
    pick = sit.Item("i-pick", "s", (right, other), right)
    assert sit.verdict(pick, "TypeError again: add --opt1")["useful"]
    assert sit.verdict(pick, "add --opt1")["pick"] and not sit.verdict(pick, "add --opt1")["useful"]
    assert sit.verdict(pick, "add --opt2")["wrong_pick"]
    assert not sit.verdict(pick, "add --opt1 and --opt2")["pick"]
    quiet = sit.Item("i-silence", "s", (other,), None)
    assert sit.verdict(quiet, "No lesson I hold covers that.")["silent"]
    assert not sit.verdict(quiet, "No lesson applies, but try --opt2")["silent"]


def test_rates_need_both_kinds_and_every_answer(sit):
    right, other = lesson(sit, "org/r", 1), lesson(sit, "org/x", 2)
    items = [sit.Item("a", "s", (right, other), right), sit.Item("b", "s", (other,), None)]
    found = sit.rates(items, {"a": "TypeError: --opt1", "b": "no lesson applies"})
    assert found == {"pick": 1.0, "useful": 1.0, "wrong_pick": 0.0, "silence": 1.0}
    with pytest.raises(KeyError):
        sit.rates(items, {"a": "x"})
    assert sit.rates(items[:1], {"a": "TypeError: --opt1"})["silence"] is None
    with pytest.raises(ValueError):
        sit.rates(items[1:], {"b": "x"})


def test_ranker_puts_the_matching_lesson_first_and_narrowing_keeps_the_answer(sit):
    right = lesson(sit, "org/r", 1)
    near = lesson(sit, "org/r", 2)
    far = [lesson(sit, "org/x", n) for n in range(3, 8)]
    item = sit.Item("i-pick", sit.situation_of(right), (*far, near, right), right)
    assert sit.lexical_rank(item)[0] is right
    top = sit.narrowed(item, 2)
    assert len(top.prompt_lessons) == 2 and right in top.prompt_lessons
    assert top.applies is right
    blind = sit.narrowed(sit.Item("i-x", sit.situation_of(right), (*far, right), right), 1)
    assert blind.applies is right  # the answer stays even if the ranker dropped it


def test_ranker_recall_and_pick_item_abstention(sit):
    right = lesson(sit, "org/r", 1)
    far = [lesson(sit, "org/x", n) for n in range(3, 8)]
    pick = sit.Item("i-pick", sit.situation_of(right), (*far, right), right)
    quiet = sit.Item("i-silence", sit.situation_of(right), tuple(far), None)
    assert sit.ranker_recall([pick, quiet], depths=(1,)) == {"recall_at_1": 1.0}
    answers = {"i-pick": "No lesson applies.", "i-silence": "No lesson applies."}
    assert sit.pick_item_abstention([pick, quiet], answers) == 1.0
