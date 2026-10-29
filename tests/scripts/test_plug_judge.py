"""Plug round 3's pairwise judge on hand-written items and scores."""

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
def judge(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_judge", ROUTEA / "plug_judge.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_judge"] = module
    spec.loader.exec_module(module)
    return module


def lesson(judge, repo, number):
    return judge.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"TypeError: boom {number}",
        error_class="TypeError",
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def items(judge):
    right = lesson(judge, "org/r", 1)
    others = tuple(lesson(judge, "org/x", n) for n in range(2, 8))
    situation = f"Ran `{right.failed}` in org/r (file {right.file}). It failed: {right.error}"
    pick = judge.Item("a-pick", situation, (*others, right), right)
    quiet = judge.Item("a-silence", situation, others, None)
    return right, others, pick, quiet


def test_rows_are_balanced_with_hard_negatives(judge):
    _, _, pick, quiet = items(judge)
    rows = judge.judge_rows([pick, quiet], size=5)
    answers = [row["messages"][2]["content"] for row in rows]
    assert answers.count("yes") == answers.count("no") == 1


def test_rows_refuse_when_negatives_cannot_balance(judge):
    right = lesson(judge, "org/r", 1)
    alone = judge.Item("b-pick", "Ran `x`", (right,), right)
    with pytest.raises(ValueError, match="balance"):
        judge.judge_rows([alone], size=5)


def test_queries_cover_the_shortlist(judge):
    _, _, pick, quiet = items(judge)
    queries = judge.judge_queries([pick, quiet], size=3)
    assert len(queries) == 6
    assert all("::" in q["question_id"] and q["context"] == judge.JUDGE_SYSTEM for q in queries)


def test_choice_takes_the_top_score_or_stays_silent(judge):
    right, others, pick, quiet = items(judge)
    scores = {f"a-pick::{one.lesson_id}": 0.1 for one in (*others, right)}
    scores |= {f"a-silence::{one.lesson_id}": 0.2 for one in others}
    scores["a-pick::org/r-1"] = 0.9
    chosen = judge.choose([pick, quiet], scores, size=7, threshold=0.5)
    assert [c.lesson_id for c in chosen] == ["org/r-1", None]
    rates = judge.outcome_rates([pick, quiet], chosen)
    assert rates == {
        "pick": 1.0,
        "silence": 1.0,
        "wrong_pick": 0.0,
        "coverage": 1.0,
        "precision": 1.0,
    }
    loud = judge.choose([pick, quiet], scores, size=7, threshold=0.0)
    assert judge.outcome_rates([pick, quiet], loud)["silence"] == 0.0


def test_threshold_is_the_lowest_meeting_the_gate_or_raises(judge):
    right, others, pick, quiet = items(judge)
    scores = {f"a-pick::{one.lesson_id}": 0.1 for one in (*others, right)}
    scores |= {f"a-silence::{one.lesson_id}": 0.3 for one in others}
    scores["a-pick::org/r-1"] = 0.9
    assert judge.fit_threshold([pick, quiet], scores, 7, [0.0, 0.25, 0.35, 0.5]) == 0.35
    scores["a-silence::org/x-2"] = 0.95
    with pytest.raises(ValueError):
        judge.fit_threshold([pick, quiet], scores, 7, [0.0, 0.5])


def test_seed_mean_scores_average_and_refuse_mismatched_files(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_judge_cli", ROUTEA / "plug_judge_cli.py")
    cli = importlib.util.module_from_spec(spec)
    sys.modules["plug_judge_cli"] = cli
    spec.loader.exec_module(cli)
    first, second, other = tmp_path / "s0.jsonl", tmp_path / "s1.jsonl", tmp_path / "x.jsonl"
    first.write_text('{"question_id": "q", "p_yes": 0.2}\n')
    second.write_text('{"question_id": "q", "p_yes": 0.6}\n')
    other.write_text('{"question_id": "z", "p_yes": 0.6}\n')
    assert cli.seed_mean_scores([first, second]) == {"q": pytest.approx(0.4)}
    with pytest.raises(ValueError):
        cli.seed_mean_scores([first, other])
