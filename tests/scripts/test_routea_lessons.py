"""LCAP lesson mining, held-out questions and deterministic scoring, on hand-written records."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from record_builders import run

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


def numbered(*records):
    from dataclasses import replace

    return [replace(r, step=i, project="org__repo") for i, r in enumerate(records)]


FAILED = run(
    "cd /workspace/org__repo__1.0 && python -m pytest tests/test_a.py -v",
    exit_code=1,
    output="E   ModuleNotFoundError: No module named 'pkg'\n[exit code 1]",
)
FIXED = run("cd /workspace/org__repo__1.0 && PYTHONPATH=src python -m pytest tests/test_a.py -v")


def test_a_failed_command_and_its_later_fix_make_one_lesson(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    drops = Counter()
    (lesson,) = lessons.lessons_in_session(numbered(FAILED, FIXED), drops)
    assert lesson.repo == "org/repo"
    assert lesson.failed == "python -m pytest tests/test_a.py -v"
    assert lesson.error_class == "ModuleNotFoundError"
    assert lesson.added == ("PYTHONPATH=src",)
    assert lesson.file == "tests/test_a.py"
    assert "run `PYTHONPATH=src python -m pytest tests/test_a.py -v` instead" in lesson.text()


def test_unusable_pairs_are_counted_by_reason_not_kept(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    assertion = run("pytest tests/test_a.py", exit_code=1, output="E   AssertionError: 1 != 2")
    cosmetic = run("pytest tests/test_a.py -q")
    no_fix = run("pytest tests/test_b.py", exit_code=1, output="TypeError: bad")
    drops = Counter()
    found = lessons.lessons_in_session(numbered(assertion, cosmetic, no_fix), drops)
    assert found == []
    assert drops["no named error, or only an AssertionError"] == 1
    assert drops["no later success on the same program and target"] == 1


def test_a_fix_made_only_of_output_flags_is_dropped(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    failed = run("pytest tests/test_a.py", exit_code=1, output="TypeError: bad")
    drops = Counter()
    assert (
        lessons.lessons_in_session(numbered(failed, run("pytest tests/test_a.py -q")), drops) == []
    )
    assert drops["fix only changes output flags"] == 1


def test_code_that_merely_names_an_error_class_is_not_the_error(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    assert lessons.error_line("    except (ValueError, TypeError):\n") is None
    assert lessons.error_line("x\nKeyError: 'k'\n") == "KeyError: 'k'"


def test_selection_nests_and_refuses_a_short_pool(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    drops = Counter()
    (one,) = lessons.lessons_in_session(numbered(FAILED, FIXED), drops)
    assert lessons.select_lessons([one], 1) == [one]
    with pytest.raises(ValueError, match="1 usable lessons, 2 asked"):
        lessons.select_lessons([one], 2)


def lesson_and_modules(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    questions = load(monkeypatch, "questions")
    scoring = load(monkeypatch, "scoring")
    (lesson,) = lessons.lessons_in_session(numbered(FAILED, FIXED), Counter())
    return lesson, questions, scoring


def test_held_out_questions_never_reuse_a_training_question(monkeypatch):
    lesson, questions, _ = lesson_and_modules(monkeypatch)
    trained = {row["messages"][1]["content"] for row in questions.training_messages(lesson)}
    held = questions.held_out_questions(lesson)
    assert len(held) == 5
    assert not trained & {q.text for q in held}
    assert {q.asks for q in held} == set(questions.Asks)


def test_recall_needs_the_exact_key_details(monkeypatch):
    lesson, questions, scoring = lesson_and_modules(monkeypatch)
    asks = questions.Asks
    note = "It hit ModuleNotFoundError; set `PYTHONPATH=src` first."
    assert scoring.recalled(note, lesson, asks.NOTE)
    assert scoring.recalled("Use PYTHONPATH=src.", lesson, asks.FIX)
    assert not scoring.recalled("Check your imports.", lesson, asks.FIX)
    assert not scoring.recalled("Use PYTHONPATH=src.", lesson, asks.NOTE)
    assert scoring.recalled("A ModuleNotFoundError.", lesson, asks.ERROR)


def test_details_no_lesson_holds_count_as_invented(monkeypatch):
    lesson, questions, scoring = lesson_and_modules(monkeypatch)
    known = scoring.vocabulary([lesson])
    faithful = scoring.score(
        "ModuleNotFoundError in tests/test_a.py", lesson, questions.Asks.ERROR, known
    )
    assert faithful.invented == ()
    made_up = scoring.score(
        "KeyError; run setup.py with --force", lesson, questions.Asks.ERROR, known
    )
    assert made_up.invented == ("--force", "KeyError", "setup.py")
    assert not made_up.hit


def write_work_dir(root, lesson, questions, answer_text):
    """A one-lesson LCAP work dir: every arm answers every question with `answer_text`."""
    import json
    from dataclasses import asdict

    (root / "data").mkdir()
    (root / "data" / "lessons.jsonl").write_text(json.dumps(asdict(lesson)) + "\n")
    held = [asdict(q) for q in questions.held_out_questions(lesson)]
    (root / "data" / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in held))
    para = [{**q, "question_id": q["question_id"] + "p"} for q in held[:2]]
    (root / "data" / "questions-para.jsonl").write_text("".join(json.dumps(q) + "\n" for q in para))
    answers = root / "answers" / "t"
    answers.mkdir(parents=True)
    rows = "".join(
        json.dumps({"question_id": q["question_id"], "answer": answer_text}) + "\n" for q in held
    )
    names = ["floor-one-100", *(f"grouped-group-{g:02d}" for g in range(10))] + [
        f"{arm}-one-{n}" for arm in ("ceiling", "adapter") for n in (10, 30, 100)
    ]
    para_rows = "".join(
        json.dumps({"question_id": q["question_id"], "answer": answer_text}) + "\n" for q in para
    )
    for name in names:
        (answers / f"{name}.jsonl").write_text(rows)
        (answers / f"para-{name}.jsonl").write_text(para_rows)
    logs = root / "logs" / "t"
    logs.mkdir(parents=True)
    (logs / "timing.txt").write_text("train-one-10 12\nlcap t done\n")
    (logs / "budget.txt").write_text("train-one-10 iters=120 rows=60\n")
    (logs / "train-one-10.log").write_text("  2000000000  peak memory footprint\n")


def test_every_arm_is_scored_beside_floor_and_ceiling(monkeypatch, tmp_path):
    lesson, questions, _ = lesson_and_modules(monkeypatch)
    score_answers = load(monkeypatch, "score_answers")
    write_work_dir(tmp_path, lesson, questions, "ModuleNotFoundError; use PYTHONPATH=src")
    scored = score_answers.score_tag(tmp_path, "t", "full", [lesson])
    roles = {row["label"]: row["role"] for row in scored["rows_template"]}
    assert roles["t floor 10"] == "floor" and roles["t ceiling 10"] == "ceiling"
    assert roles["t adapter 100"] == roles["t grouped 100"] == "under test"
    every = scored["rows_template"] + scored["rows_paraphrase"]
    assert all(row["recall"] == 1.0 and row["invented_rate"] == 0.0 for row in every)
    assert {row["questions"] for row in scored["rows_paraphrase"]} == {2}
    assert scored["training"]["one-10"] == {"iters": 120, "seconds": 12, "peak_mem_gb": 2.0}


def test_a_missing_answer_file_stops_scoring(monkeypatch, tmp_path):
    lesson, questions, _ = lesson_and_modules(monkeypatch)
    score_answers = load(monkeypatch, "score_answers")
    write_work_dir(tmp_path, lesson, questions, "x")
    (tmp_path / "answers" / "t" / "adapter-one-30.jsonl").unlink()
    with pytest.raises(FileNotFoundError, match="adapter-one-30"):
        score_answers.score_tag(tmp_path, "t", "full", [lesson])


def test_the_top_matrix_scores_only_the_100_lesson_cells(monkeypatch, tmp_path):
    lesson, questions, _ = lesson_and_modules(monkeypatch)
    score_answers = load(monkeypatch, "score_answers")
    write_work_dir(tmp_path, lesson, questions, "x")
    (tmp_path / "answers" / "t" / "adapter-one-30.jsonl").unlink()
    scored = score_answers.score_tag(tmp_path, "t", "top", [lesson])
    labels = [row["label"] for row in scored["rows_template"]]
    assert labels == ["t floor 100", "t ceiling 100", "t adapter 100"]


def test_a_paraphrase_must_keep_the_repo_and_the_command(monkeypatch):
    rules = load(monkeypatch, "paraphrase_rules")
    original = "Which exception did `pytest tests/a.py` hit in org/repo?"
    assert rules.keeps_details(
        original, "In org/repo, `pytest tests/a.py` raised what?", "org/repo", "tests/a.py"
    )
    assert not rules.keeps_details(
        original, "What did pytest raise in org/repo?", "org/repo", "tests/a.py"
    )
    assert not rules.keeps_details(
        original, "`pytest tests/a.py` raised what?", "org/repo", "tests/a.py"
    )
    assert not rules.keeps_details(original, original, "org/repo", "tests/a.py")
    plain = "Before I run pytest against tests/a.py in org/repo, anything to know?"
    assert rules.keeps_details(
        plain, "Any warning for tests/a.py with pytest in org/repo?", "org/repo", "tests/a.py"
    )


def test_the_sizes_matrix_scores_every_size_without_grouped_adapters(monkeypatch, tmp_path):
    lesson, questions, _ = lesson_and_modules(monkeypatch)
    score_answers = load(monkeypatch, "score_answers")
    write_work_dir(tmp_path, lesson, questions, "x")
    for grouped in (tmp_path / "answers" / "t").glob("*grouped-*"):
        grouped.unlink()
    (tmp_path / "logs" / "t" / "train-one-10.log").write_text(
        "64000000000 peak memory footprint (torch max reserved)\n"
    )
    scored = score_answers.score_tag(tmp_path, "t", "sizes", [lesson])
    labels = [row["label"] for row in scored["rows_template"]]
    assert labels == [
        f"t {arm} {n}" for arm in ("floor", "ceiling", "adapter") for n in (10, 30, 100)
    ]
    assert scored["training"]["one-10"]["peak_mem_gb"] == 64.0
