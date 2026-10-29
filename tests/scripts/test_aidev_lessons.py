"""AIDev lessons and Route B rows on hand-written comments and commits."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

AIDEV = Path(__file__).resolve().parents[2] / "scripts" / "aidev"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(AIDEV))
    spec = importlib.util.spec_from_file_location(name, AIDEV / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ADD = "@@ -1,1 +1,3 @@ def fetch(url):\n a\n+call()\n+more()\n"
FIX = "@@ -2,1 +2,2 @@\n-call()\n+try_call()\n+check()\n"


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("Please add a unit test for this branch.", "tests_missing"),
        ("This swallows the exception; let it propagate.", "error_handling"),
        ("This belongs in the utils module.", "wrong_module"),
        ("`foo()` is deprecated, use bar instead.", "api_misuse"),
        ("Please rename this to match our naming convention.", "naming_convention"),
    ],
)
def test_classify_names_each_general_kind(monkeypatch, body, kind):
    lessons = load(monkeypatch, "lessons")
    assert lessons.classify(body) == lessons.IssueKind(kind)


def test_classify_returns_none_for_a_comment_of_no_general_kind(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    assert lessons.classify("Looks good to me, thanks!") is None


def test_test_paths(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    assert lessons.is_test_path("pkg/tests/test_x.py")
    assert lessons.is_test_path("test_x.py")
    assert not lessons.is_test_path("pkg/latest.py")


def flagged_pr(monkeypatch, patches):
    hunks, flags = load(monkeypatch, "hunks"), load(monkeypatch, "flags")
    commits = [
        flags.Commit(f"s{i}", {path: flags.FileState("modified", tuple(hunks.parse_patch(p)))})
        for i, (path, p) in enumerate(patches)
    ]
    comment = flags.Comment(1, "s0", "pkg/net.py", 3, human=True)
    labels = flags.label_pr(commits, [comment])
    (unit,) = [u for u in labels.units if u.human_at is not None]
    return commits, unit


def test_resolution_is_the_rework_with_line_counts(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    commits, unit = flagged_pr(monkeypatch, [("pkg/net.py", ADD), ("pkg/net.py", FIX)])
    fix = lessons.resolution(unit, commits, lessons.IssueKind.ERROR_HANDLING)
    assert (fix.commit_index, fix.added, fix.removed, fix.tests_changed) == (1, 2, 1, False)


def test_missing_tests_are_resolved_by_a_later_test_change(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    test_patch = "@@ -1,1 +1,2 @@\n a\n+def test_fetch(): ...\n"
    commits, unit = flagged_pr(
        monkeypatch, [("pkg/net.py", ADD), ("tests/test_net.py", test_patch)]
    )
    assert lessons.resolution(unit, commits, lessons.IssueKind.ERROR_HANDLING) is None
    fix = lessons.resolution(unit, commits, lessons.IssueKind.TESTS_MISSING)
    assert fix.tests_changed and fix.added == 0


def lesson_of(lessons, repo="octo/widgets", kind="error_handling"):
    fix = lessons.Resolution(1, 2, 1, tests_changed=False)
    return lessons.Lesson(
        "abc123", repo, "Copilot", lessons.IssueKind(kind), "pkg/net.py", "fetch", fix
    )


def test_lesson_reads_as_three_parts_of_template_prose(monkeypatch):
    lessons = load(monkeypatch, "lessons")
    lesson = lesson_of(lessons)
    assert "`fetch` in `pkg/net.py`" in lesson.what_happened()
    assert lesson.how_resolved() == (
        "A later commit in the same pull request reworked those lines (2 added, 1 removed)."
    )
    assert lesson.text().endswith(lesson.check())


def test_rows_are_chat_rows_without_repeats(monkeypatch):
    lessons, training = load(monkeypatch, "lessons"), load(monkeypatch, "training")
    first = lesson_of(lessons)
    rows = training.rows_for([first, first])
    assert len(rows) == len(training.training_pairs(first))
    roles = [[m["role"] for m in row["messages"]] for row in rows]
    assert all(r == ["system", "user", "assistant"] for r in roles)


def test_split_holds_out_whole_repositories_up_to_the_share(monkeypatch):
    training = load(monkeypatch, "training")
    per_repo = {f"org/repo{i}": 1 + i % 3 for i in range(40)}
    splits = training.assign_splits(per_repo)
    assert set(splits) == set(per_repo)
    held = sum(n for repo, n in per_repo.items() if splits[repo] is training.Split.HELD_OUT)
    assert held >= training.HELD_OUT_SHARE * sum(per_repo.values())
    assert set(splits.values()) == set(training.Split)
    assert training.assign_splits(per_repo) == splits


def test_held_out_questions_use_wordings_never_trained_on(monkeypatch):
    lessons, training = load(monkeypatch, "lessons"), load(monkeypatch, "training")
    lesson = lesson_of(lessons)
    trained = {q for q, _ in training.training_pairs(lesson)}
    asked = {q["text"] for q in training.held_out_questions(lesson)}
    assert asked and not asked & trained


def test_results_document_passes_the_results_content_gate(monkeypatch):
    report, lessons = load(monkeypatch, "report"), load(monkeypatch, "lessons")
    build = load(monkeypatch, "build")
    tally = build.Tally()
    tally.add_unit("Copilot", _unit(monkeypatch), 1, 0)
    document = report.results_document(tally, [lesson_of(lessons)], [lesson_of(lessons)], {})
    assert {r["arm"] for r in document["rows"]} == {"human_flagged"}
    gate = load_gate()
    assert gate.findings_in("aidev.json", json.loads(json.dumps(document))) == []


def _unit(monkeypatch):
    _, unit = flagged_pr(monkeypatch, [("pkg/net.py", ADD), ("pkg/net.py", FIX)])
    return unit


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "check_results_content", ROOT / "scripts" / "gates" / "check_results_content.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_habit_scorer_counts_hits_off_kind_and_misses(monkeypatch):
    scorer = load(monkeypatch, "score_habits")
    questions = [
        {"question_id": "a", "kind": "tests_missing"},
        {"question_id": "b", "kind": "error_handling"},
        {"question_id": "c", "kind": "api_misuse"},
    ]
    answers = {"a": "Add a test first.", "b": "Add a test first.", "c": "Looks fine."}
    result = scorer.score(questions, answers)
    assert result["overall"] == {"hit": 1, "off_kind": 1, "miss": 1}
    with pytest.raises(KeyError):
        scorer.score(questions, {"a": "x"})
