"""The general-lessons builder on hand-written runs, fixes and texts."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
DUCK = "sqlglot/dialects/duckdb.py"
FIX = f"""diff --git a/{DUCK} b/{DUCK}
--- a/{DUCK}
+++ b/{DUCK}
@@ -3,1 +3,2 @@ class DuckDB(Dialect):
             exp.Old: rename_func("OLD"),
+            exp.Brand: rename_func("BRAND_NEW_NAME"),
"""
TEST_PATCH = "+        self.validate_identity('SELECT 1')\n"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEB))
    spec = importlib.util.spec_from_file_location(name, ROUTEB / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def facts(monkeypatch, **changes):
    runs = load(monkeypatch, "sqlglot_runs")
    base = dict(
        instance_id="t",
        run_id="r",
        resolved=False,
        step_limit=50,
        steps=50,
        first_view={DUCK: 3},
        rereads={DUCK: 9},
        first_edit=None,
        edited=(),
        scratch_scripts=0,
        verified_test=None,
        traps=(),
    )
    return runs.RunFacts(**(base | changes))


def run(monkeypatch, task="t-1", resolved=False, submitted=False, commands=(), **changes):
    general_runs = load(monkeypatch, "general_runs")
    return general_runs.PlainRun(
        task=task,
        log="runs",
        step_limit=50,
        resolved=resolved,
        exit_status="x",
        submitted=submitted,
        facts=facts(monkeypatch, resolved=resolved, **changes),
        commands=tuple(commands),
    )


GOLD = {"t-1": (DUCK,), "t-2": (DUCK,), "t-3": (DUCK,)}


def test_habit_detectors(monkeypatch):
    habits = load(monkeypatch, "general_habits")
    stalled = run(monkeypatch)
    assert habits.found_not_edited(stalled, GOLD) and habits.never_edited(stalled, GOLD)
    assert habits.scratch_not_edit(run(monkeypatch, scratch_scripts=6), GOLD)
    late = run(monkeypatch, first_edit=40, edited=(DUCK,))
    assert habits.late_first_edit(late, GOLD) and not habits.wrong_layer(late, GOLD)
    assert habits.wrong_layer(run(monkeypatch, first_edit=9, edited=("sqlglot/parser.py",)), GOLD)
    green = run(monkeypatch, first_edit=9, edited=(DUCK,), verified_test="python -m unittest x")
    assert habits.passing_not_submitted(green, GOLD)
    assert habits.whole_suite(run(monkeypatch, commands=["python -m unittest discover"]), GOLD)
    assert habits.targeted_test(
        run(monkeypatch, commands=["python -m unittest tests.test_x"]), GOLD
    )
    assert not habits.whole_suite(run(monkeypatch, commands=["python -m unittest tests.x"]), GOLD)


def test_counts_and_timing(monkeypatch):
    habits = load(monkeypatch, "general_habits")
    runs = [
        run(monkeypatch, "t-1"),
        run(monkeypatch, "t-2", resolved=True, submitted=True, first_edit=10, edited=(DUCK,)),
        run(monkeypatch, "t-3", first_edit=40, edited=(DUCK,)),
    ]
    found = habits.count(runs, GOLD, habits.never_edited)
    assert (found.runs, found.tasks, found.solved, found.solved_without) == (1, 1, 0, 1)
    timing = habits.edit_timing(runs)
    assert (timing["early_solved"], timing["early_runs"], timing["never_runs"]) == (1, 1, 1)
    assert habits.edit_to_end(runs) == 40
    assert habits.submissions(runs) == {"submitted": 1, "submitted_solved": 1}
    assert habits.view_to_edit_gap(runs, GOLD) == 7


def test_habit_lessons_keep_only_habits_seen_in_several_tasks(monkeypatch):
    lessons = load(monkeypatch, "general_habit_lessons")
    runs = [run(monkeypatch, f"t-{i}", scratch_scripts=6) for i in (1, 2, 3)]
    kept = {lesson.lesson_id: lesson for lesson in lessons.habit_lessons(runs, GOLD)}
    assert "habit-repro-once" in kept and "habit-check-the-layer" not in kept
    assert kept["habit-repro-once"].support["tasks"] == 3
    assert not any(ch.isdigit() for ch in kept["habit-repro-once"].card())


def place(monkeypatch, file, name):
    return load(monkeypatch, "sqlglot_places").Place(file, name)


@pytest.mark.parametrize(
    ("file", "name", "kind"),
    [
        (DUCK, "DuckDB.Generator.TRANSFORMS", "dialect Generator.TRANSFORMS map"),
        (DUCK, "DuckDB.Generator.foo_sql", "dialect Generator method or type map"),
        (DUCK, "DuckDB.Parser.FUNCTIONS", "dialect Parser function map"),
        (DUCK, "DuckDB.Parser._parse_x", "dialect Parser _parse_ method"),
        (DUCK, "DuckDB.Tokenizer.KEYWORDS", "dialect Tokenizer keywords"),
        (DUCK, "DuckDB", "dialect class setting"),
        (DUCK, "module level", "dialect module helper or import"),
        ("sqlglot/parser.py", "Parser._parse_x", "shared parser.py"),
        ("sqlglot/optimizer/x.py", "f", "other module"),
    ],
)
def test_place_kinds(monkeypatch, file, name, kind):
    places = load(monkeypatch, "general_places")
    assert str(places.place_kind(place(monkeypatch, file, name))) == kind


def test_entry_reuse_count_reuse_of_an_existing_helper(monkeypatch):
    places = load(monkeypatch, "general_places")
    assert places.entry_reuse(FIX, {DUCK: "from x import rename_func"}) == (1, 1)
    assert places.entry_reuse(FIX, {DUCK: "nothing here"}) == (0, 1)
    assert places.entry_reuse(FIX, {}) == (0, 0)


def task(
    monkeypatch, name="s-1", kind="feature", places_=(), tests=("tests.dialects.test_duckdb",)
):
    evidence = load(monkeypatch, "general_evidence")
    kinds = sys.modules["general_kinds"]
    return evidence.SourceTask(
        task=name,
        kind=kinds.TaskKind(kind),
        title="Support X",
        gold_files=(DUCK,),
        places=tuple(places_),
        test_modules=tests,
        test_patch=TEST_PATCH,
        gold_patch=FIX,
        places_resolved=True,
        entry_reuse=(1, 1),
    )


def test_knowledge_and_implementation_lessons_count_tasks(monkeypatch):
    transforms = place(monkeypatch, DUCK, "DuckDB.Generator.TRANSFORMS")
    shared = place(monkeypatch, "sqlglot/parser.py", "Parser._parse_x")
    tasks = [
        task(monkeypatch, "s-1", places_=[transforms]),
        task(monkeypatch, "s-2", "bug", [shared]),
    ]
    knowledge = load(monkeypatch, "general_knowledge")
    implementation = load(monkeypatch, "general_implementation")
    found = {lesson.lesson_id: lesson for lesson in knowledge.knowledge_lessons(tasks)}
    assert found["repo-dialect-output"].support == {
        "tasks": 1,
        "transforms_tasks": 1,
        "of_tasks": 2,
    }
    assert found["repo-shared-layer"].source_tasks == ("s-2",)
    assert found["repo-test-layout"].support["validate_tasks"] == 2
    built = implementation.implementation_lessons(knowledge.features(tasks))
    by_id = {lesson.lesson_id: lesson for lesson in built}
    assert by_id["impl-mirror-neighbor"].support["entries_reused"] == 1
    assert by_id["impl-new-function"].source_tasks == ("s-1",)


def test_refuse_evaluation_raises_on_an_eval_task_or_run(monkeypatch):
    evidence = load(monkeypatch, "general_evidence")
    clean = evidence.Evidence({"s-1": task(monkeypatch)}, (), frozenset({"e-1"}), {}, {})
    assert evidence.refuse_evaluation(clean) is clean
    leaked = evidence.Evidence({}, (run(monkeypatch, "e-1"),), frozenset({"e-1"}), {}, {})
    with pytest.raises(evidence.EvaluationLeakError, match="e-1"):
        evidence.refuse_evaluation(leaked)
    assert evidence.test_modules(["tests/dialects/test_duckdb.py::T::t", "x.py::y"]) == (
        "tests.dialects.test_duckdb",
    )


def test_scan_refuses_gold_lines_and_specific_names_but_not_conventions(monkeypatch):
    leakage = load(monkeypatch, "general_leakage")
    common = leakage.conventions([FIX] * 5)
    assert "rename_func" in common
    evaluation = {"e-1": FIX.replace("BRAND_NEW_NAME", "UNIQUE_NAME")}
    assert leakage.scan({"a": "use `rename_func` in TRANSFORMS"}, evaluation, common)["hits"] == 0
    with pytest.raises(sys.modules["sqlglot_leakage"].LeakageError, match="e-1"):
        leakage.scan({"a": 'exp.Brand: rename_func("UNIQUE_NAME"),'}, evaluation, common)
    with pytest.raises(sys.modules["sqlglot_leakage"].LeakageError, match="name"):
        leakage.scan({"a": "map UNIQUE_NAME"}, evaluation, common)
    assert leakage.leaking_keys({"a": "UNIQUE_NAME", "b": "fine"}, evaluation, common) == {"a"}


def test_pattern_close_names_lessons_that_teach_the_eval_fix_kind(monkeypatch):
    leakage = load(monkeypatch, "general_leakage")
    lesson_module = sys.modules["general_lesson"]
    lesson = lesson_module.GeneralLesson(
        "l",
        lesson_module.LessonKind.REPO,
        "s",
        "h",
        "r",
        "c",
        teaches=("dialect Generator.TRANSFORMS map",),
    )
    transforms = place(monkeypatch, DUCK, "DuckDB.Generator.TRANSFORMS")
    assert leakage.pattern_close([lesson], {"e-1": [transforms], "e-2": []}) == {
        "e-1": ["l"],
        "e-2": [],
    }


def _lessons(monkeypatch):
    lesson_module = load(monkeypatch, "general_lesson")
    support = {
        "never_edited_runs": 4,
        "of_runs": 9,
        "early_solved": 2,
        "early_runs": 3,
        "tasks": 5,
        "of_tasks": 7,
    }
    return {
        lesson_id: lesson_module.GeneralLesson(
            lesson_id, lesson_module.LessonKind.HABIT, "S.", "h", "r", "c", support
        )
        for lesson_id in ("habit-edit-once-found", "repo-shared-layer", "impl-new-function")
    }


def test_card_is_prose_without_counts_and_stays_short(monkeypatch):
    lessons = _lessons(monkeypatch)
    card = load(monkeypatch, "general_card")
    text = card.card(lessons)
    body = "\n".join(line.split(". ", 1)[-1] for line in text.splitlines())
    assert "never solved" in text and not any(ch.isdigit() for ch in body)
    assert len(text.split()) <= card.MAX_WORDS
    monkeypatch.setattr(card, "MAX_WORDS", 10)
    with pytest.raises(card.CardTooLongError):
        card.card(lessons)


def test_rows_teach_lessons_and_correct_stalled_runs(monkeypatch):
    rows = load(monkeypatch, "general_rows")
    lesson = _lessons(monkeypatch)["habit-edit-once-found"]
    assert [row.kind for row in rows.lesson_rows(lesson)] == ["card", "resolved", "check"]
    transforms = place(monkeypatch, DUCK, "DuckDB.Generator.TRANSFORMS")
    tasks = {"t-1": task(monkeypatch, "t-1", "bug", [transforms])}
    (row,) = rows.action_rows([run(monkeypatch, "t-1")], tasks, GOLD)
    assert row.lesson_id == "habit-edit-once-found"
    assert "read it 10 times" in row.messages[1]["content"]
    assert "Generator.TRANSFORMS" in row.messages[2]["content"]
    assert rows.action_rows([run(monkeypatch, "t-9")], tasks, GOLD) == []
    question = rows.recall_question(lesson)
    assert question["question_id"] == "habit-edit-once-found-q"
