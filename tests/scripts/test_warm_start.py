"""Warm-start plan, probes, recall and paired bootstrap, on hand-written lessons."""

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


def load(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("warm_start", ROUTEA / "warm_start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["warm_start"] = module
    spec.loader.exec_module(module)
    return module


def lesson(module, repo, number, error="TypeError", added=("--flag",)):
    return module.Lesson(
        lesson_id=f"{number:04d}",
        repo=repo,
        program="pytest",
        file="tests/test_a.py",
        failed="pytest tests/test_a.py",
        error=f"{error}: boom",
        error_class=error,
        fix="pytest tests/test_a.py --flag",
        added=added,
    )


def test_repos_need_ten_distinct_lessons_and_blocked_repos_drop(monkeypatch):
    ws = load(monkeypatch)
    many = [lesson(ws, "org/many", n, added=(f"--f{n}",)) for n in range(12)]
    repeats = [lesson(ws, "org/repeats", n) for n in range(12)]  # one distinct failure
    blocked = [lesson(ws, "iterative/dvc", n, added=(f"--f{n}",)) for n in range(12)]
    by_repo = ws.distinct_by_repo(many + repeats + blocked)
    assert list(by_repo) == ["org/many"]
    assert ws.budgets_for(by_repo["org/many"]) == [5, 10]


def test_probes_hold_every_training_question_and_the_reworded_ones(monkeypatch):
    ws = load(monkeypatch)
    found = ws.probes([lesson(ws, "org/a", 1)])
    wordings = [probe["wording"] for probe in found]
    assert wordings.count("verbatim") == 6
    assert wordings.count("paraphrased") == 5


def test_recall_by_wording_scores_and_refuses_a_missing_answer(monkeypatch):
    ws = load(monkeypatch)
    item = lesson(ws, "org/a", 1)
    found = ws.probes([item])
    answers = {p["question_id"]: "It raised TypeError; add --flag." for p in found}
    assert ws.recall_by_wording(found, answers, [item]) == {"verbatim": 1.0, "paraphrased": 1.0}
    with pytest.raises(KeyError):
        ws.recall_by_wording(found, {}, [item])


def test_paired_gain_interval_brackets_the_mean(monkeypatch):
    ws = load(monkeypatch)
    result = ws.paired_gain([0.1, 0.2, 0.3, 0.0], resamples=2000)
    assert result["repos"] == 4
    assert result["ci95_low"] <= result["mean_gain"] == 0.15 <= result["ci95_high"]
    with pytest.raises(ValueError):
        ws.paired_gain([])


def test_curve_labels_plain_as_reference_and_habits_under_test(monkeypatch):
    ws = load(monkeypatch)
    cell = {"verbatim": 0.5, "paraphrased": 0.25, "habits": 0.1}
    better = {"verbatim": 0.75, "paraphrased": 0.5, "habits": 0.6}
    cells = {("plain", "r1", 5): cell, ("habits", "r1", 5): better}
    cells |= {("plain", "r2", 5): cell, ("habits", "r2", 5): better}
    rows = ws.curve(cells)
    assert [(r["arm"], r["role"]) for r in rows] == [
        ("plain_start", "reference"),
        ("habits_start", "under_test"),
    ]
    assert ws.gains(cells)["paraphrased_at_5"]["mean_gain"] == 0.25


def load_l2l(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("l2l_quick", ROUTEA / "l2l_quick.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["l2l_quick"] = module
    spec.loader.exec_module(module)
    return module


def test_windows_keep_a_short_tail_with_the_group_before(monkeypatch):
    l2l = load_l2l(monkeypatch)
    sizes = [len(group) for group in l2l.windows(list(range(7)))]
    assert sizes == [3, 4]


def test_meta_rows_answer_from_context_and_abstain_without_it(monkeypatch):
    l2l = load_l2l(monkeypatch)
    by_repo = {
        repo: [lesson(l2l, repo, n + offset, added=(f"--f{n}",)) for n in range(3)]
        for repo, offset in (("org/a", 0), ("org/b", 100))
    }
    rows = l2l.meta_rows(by_repo)
    answers = [row["messages"][2]["content"] for row in rows]
    assert answers.count(l2l.ABSTAIN) == 6
    assert len(rows) == 6 * 6 + 6
    for row in rows:
        if row["messages"][2]["content"] == l2l.ABSTAIN:
            continue
        assert "What you remember:" in row["messages"][0]["content"]
