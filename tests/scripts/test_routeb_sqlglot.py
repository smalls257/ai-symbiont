"""The sqlglot Route B lesson builder on hand-written runs, sources and diffs (no real data)."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

SOURCE = """import re


class Duck(Dialect):
    class Generator(Generator):
        TRANSFORMS = {
            exp.A: rename("A"),
            exp.B: rename("B"),
        }

        def lower(self, e):
            return e


def helper():
    return 1
"""

ENTRY_DIFF = """diff --git a/sqlglot/duck.py b/sqlglot/duck.py
--- a/sqlglot/duck.py
+++ b/sqlglot/duck.py
@@ -6,3 +6,4 @@ class Duck(Dialect):
         TRANSFORMS = {
             exp.A: rename("A"),
+            exp.C: rename("C"),
             exp.B: rename("B"),
"""

METHOD_DIFF = """diff --git a/sqlglot/duck.py b/sqlglot/duck.py
--- a/sqlglot/duck.py
+++ b/sqlglot/duck.py
@@ -10,4 +10,7 @@ class Duck(Dialect):

         def lower(self, e):
             return e
+
+        def upper(self, e):
+            return e

"""

BODY_DIFF = """diff --git a/sqlglot/duck.py b/sqlglot/duck.py
--- a/sqlglot/duck.py
+++ b/sqlglot/duck.py
@@ -15,2 +15,2 @@ class Duck(Dialect):
 def helper():
-    return 1
+    return 2
"""

TIER1_TASK = "tobymao__sqlglot-1944"
TIER2_TASK = "tobymao__sqlglot-910"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(SCRIPTS / "routeb"))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "routeb" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def names(places):
    return [place.name for place in places]


def test_a_new_mapping_entry_is_placed_in_the_mapping(monkeypatch):
    found = load(monkeypatch, "sqlglot_places").places(ENTRY_DIFF, {"sqlglot/duck.py": SOURCE})
    assert names(found) == ["Duck.Generator.TRANSFORMS"]


def test_a_method_added_after_the_last_one_is_placed_in_its_class(monkeypatch):
    found = load(monkeypatch, "sqlglot_places").places(METHOD_DIFF, {"sqlglot/duck.py": SOURCE})
    assert names(found) == ["Duck.Generator"]


def test_a_changed_function_body_is_placed_in_the_function(monkeypatch):
    found = load(monkeypatch, "sqlglot_places").places(BODY_DIFF, {"sqlglot/duck.py": SOURCE})
    assert names(found) == ["helper"]


def message(role, command="", output="", code=0):
    if role == "assistant":
        return {"role": role, "content": "", "extra": {"actions": [{"command": command}]}}
    return {"role": role, "content": output, "extra": {"returncode": code, "raw_output": output}}


def a_run(monkeypatch):
    runs = load(monkeypatch, "sqlglot_runs")
    messages = [
        message("assistant", "grep -n TRANSFORMS sqlglot/duck.py"),
        message("tool", output="6: TRANSFORMS"),
        message("assistant", "cat > /tmp/repro.py <<'EOF'\nprint(1)\nEOF"),
        message("tool"),
        message("assistant", "python -m pytest tests/test_duck.py"),
        message("tool", output="No module named pytest", code=1),
        message("assistant", "sed -n '1,20p' sqlglot/duck.py"),
        message("tool"),
        message("assistant", "sed -i 's/A/C/' sqlglot/duck.py"),
        message("tool"),
        message("assistant", "python -m unittest -v tests.test_duck 2>&1 | tail -3"),
        message("tool", output="Ran 3 tests\n\nOK"),
    ]
    result = {"instance_id": "t-1", "resolved": True, "step_limit": 50, "steps": 6}
    return runs, runs.run_facts(result, "runs/screen-run1-low", messages)


def test_run_facts_count_views_scratch_scripts_edit_and_the_passing_test(monkeypatch):
    runs, facts = a_run(monkeypatch)
    assert facts.first_view == {"sqlglot/duck.py": 1}
    assert facts.rereads == {"sqlglot/duck.py": 1}
    assert facts.scratch_scripts == 1
    assert (facts.first_edit, facts.edited) == (5, ("sqlglot/duck.py",))
    assert facts.verified_test == "python -m unittest tests.test_duck"
    assert facts.traps == (runs.Trap.PYTEST_MISSING,)


def test_a_failing_unittest_run_is_not_a_verified_test(monkeypatch):
    runs = load(monkeypatch, "sqlglot_runs")
    failed = runs.Step("python -m unittest tests.test_duck", 1, "FAILED (failures=1)")
    assert runs.passing_modules(failed) == []


GOLD = """diff --git a/sqlglot/q.py b/sqlglot/q.py
@@ -1,2 +1,3 @@ class Q:
 class Q:
+    is_var_len_args = True
     arg_types = {"this": True}
"""


def test_a_pasted_gold_line_stops_the_build(monkeypatch):
    leakage = load(monkeypatch, "sqlglot_leakage")
    gold = {"t-910": leakage.gold_lines(GOLD)}
    with pytest.raises(leakage.LeakageError, match="t-910"):
        leakage.refuse_leaks({"row1": "Set   is_var_len_args = True  on the class."}, gold)


def test_a_backticked_code_fragment_of_a_gold_line_stops_the_build(monkeypatch):
    leakage = load(monkeypatch, "sqlglot_leakage")
    gold = {"t-1": {'exp.ParseJSON: rename_func("JSON_PARSE"),'}}
    with pytest.raises(leakage.LeakageError):
        leakage.refuse_leaks({"row": 'Map it to `rename_func("JSON_PARSE")`.'}, gold)


def test_naming_the_place_of_a_fix_is_not_a_leak(monkeypatch):
    leakage = load(monkeypatch, "sqlglot_leakage")
    gold = {"t-1": leakage.gold_lines(GOLD) | {'exp.ParseJSON: rename_func("JSON_PARSE"),'}}
    text = "Add an entry for `exp.ParseJSON` in `Redshift.Generator.TRANSFORMS`; edit class `Q`."
    assert leakage.refuse_leaks({"row": text}, gold) == 1


def a_place(monkeypatch, name="Duck.Generator.TRANSFORMS"):
    return load(monkeypatch, "sqlglot_places").Place("sqlglot/duck.py", name)


def evidence(monkeypatch, task, created, runs, place):
    lessons = load(monkeypatch, "sqlglot_lessons")
    return lessons.TaskEvidence(
        task=task,
        title="Duck output is wrong",
        created=created,
        test="python -m unittest tests.test_duck",
        gold_places=(place,),
        runs=tuple(runs),
    )


def facts(monkeypatch, resolved, first_edit=None, opened=4):
    runs = load(monkeypatch, "sqlglot_runs")
    return runs.RunFacts(
        instance_id="t",
        run_id=f"runs/screen-run{int(resolved)}-low",
        resolved=resolved,
        step_limit=50,
        steps=30 if resolved else 50,
        first_view={"sqlglot/duck.py": opened},
        rereads={"sqlglot/duck.py": 5},
        first_edit=first_edit,
        edited=("sqlglot/duck.py",) if first_edit else (),
        scratch_scripts=3,
        verified_test="python -m unittest tests.test_duck" if resolved else None,
        traps=(),
    )


def test_a_tier2_task_gives_no_lesson_and_a_later_fix_of_its_construct_is_dropped(monkeypatch):
    select = load(monkeypatch, "sqlglot_select")
    place = a_place(monkeypatch)
    evidence_by_task = {
        TIER2_TASK: evidence(
            monkeypatch, TIER2_TASK, "2023-01", [facts(monkeypatch, False)], place
        ),
        "tobymao__sqlglot-5000": evidence(
            monkeypatch, "tobymao__sqlglot-5000", "2024-01", [facts(monkeypatch, False)], place
        ),
        "tobymao__sqlglot-5001": evidence(
            monkeypatch, "tobymao__sqlglot-5001", "2022-01", [facts(monkeypatch, False)], place
        ),
    }
    chosen = select.select(evidence_by_task, {})
    assert chosen.drops == Counter({select.Drop.TIER2_OWN: 1, select.Drop.LATER_SAME_PLACE: 1})
    assert [lesson.lesson_id for lesson in chosen.lessons] == ["fail-5001"]


CURATED = {
    TIER1_TASK: {
        "link": "same-task",
        "happened": "The unit printed as None.",
        "resolved": "The entry in `Duck.Generator.TRANSFORMS` rendered the raw unit.",
        "check": "python -m unittest tests.test_duck",
        "file": "sqlglot/duck.py",
        "place": "`Duck.Generator.TRANSFORMS`",
    },
    TIER2_TASK: {
        "link": "pair-lesson",
        "from_tasks": [TIER1_TASK],
        "situation": "A Duck function prints the wrong name",
        "happened": "In an earlier task, a Duck function printed wrong.",
        "resolved": "Duck output lives in `Duck.Generator.TRANSFORMS`.",
        "check": "python -m unittest tests.test_duck",
        "file": "sqlglot/duck.py",
        "place": "`Duck.Generator.TRANSFORMS`",
    },
}


def test_tier1_lesson_links_its_own_task_and_the_pair_it_feeds(monkeypatch):
    select = load(monkeypatch, "sqlglot_select")
    lessons = load(monkeypatch, "sqlglot_lessons")
    runs = [facts(monkeypatch, True, first_edit=20), facts(monkeypatch, False)]
    found = {TIER1_TASK: evidence(monkeypatch, TIER1_TASK, "2023-01", runs, a_place(monkeypatch))}
    chosen = {lesson.lesson_id: lesson for lesson in select.select(found, CURATED).lessons}
    assert chosen["own-1944"].links == (
        (TIER1_TASK, lessons.Link.SAME_TASK),
        (TIER2_TASK, lessons.Link.PAIR_SOURCE),
    )
    assert chosen["pair-910"].links == ((TIER2_TASK, lessons.Link.PAIR_LESSON),)
    assert chosen["pair-910"].runs == chosen["own-1944"].runs
    assert "Duck output is wrong" not in chosen["pair-910"].card()


def test_a_late_edit_stall_is_never_described_as_no_edit(monkeypatch):
    lessons = load(monkeypatch, "sqlglot_lessons")
    rows = load(monkeypatch, "sqlglot_rows")
    runs = [facts(monkeypatch, True, first_edit=20), facts(monkeypatch, False, first_edit=44)]
    lesson = lessons.own_solve(
        evidence(monkeypatch, "t-1", "2023-01", runs, a_place(monkeypatch)), "own-1"
    )
    stalled = [row for row in rows.training_rows(lesson) if row.kind == "stalled"]
    asked = stalled[0].messages[1]["content"]
    assert "it is step 43 and you have not edited it" in asked
    assert "made no edit" not in asked
    assert "first edit at step 20 of 50" in lesson.resolved


def test_rows_use_glimmers_low_reasoning_turn_and_held_out_wording_is_never_trained(monkeypatch):
    lessons = load(monkeypatch, "sqlglot_lessons")
    rows = load(monkeypatch, "sqlglot_rows")
    runs = [facts(monkeypatch, False)]
    lesson = lessons.own_failure(
        evidence(monkeypatch, "t-2", "2023-01", runs, a_place(monkeypatch)), "fail-2"
    )
    made = rows.training_rows(lesson)
    assert [row.kind for row in made] == ["card", "resolved", "check", "opened", "stalled"]
    assert all(row.messages[0]["content"].endswith("Reasoning strength: low.") for row in made)
    prompts = {row.messages[1]["content"] for row in made}
    assert rows.held_out_question(lesson)["text"] not in prompts


def test_a_habit_lesson_has_no_fix_place_question(monkeypatch):
    habits = load(monkeypatch, "sqlglot_habits")
    rows = load(monkeypatch, "sqlglot_rows")
    runs = load(monkeypatch, "sqlglot_runs")
    trapped = facts(monkeypatch, False)
    trapped = type(trapped)(**{**trapped.__dict__, "traps": (runs.Trap.PYTEST_MISSING,)})
    (lesson,) = habits.habits([trapped, facts(monkeypatch, True)])
    assert lesson.happened.startswith("In 1 of 2 sqlglot runs")
    assert [row.kind for row in rows.training_rows(lesson)] == ["card", "habit"]


def test_failing_tests_become_one_unittest_command(monkeypatch):
    lessons = load(monkeypatch, "sqlglot_lessons")
    tests = ["tests/dialects/test_duck.py::TestDuck::test_a", "tests/dialects/test_duck.py::T::b"]
    assert lessons.test_command(tests) == "python -m unittest tests.dialects.test_duck"
    with pytest.raises(ValueError, match="no unittest module"):
        lessons.test_command(["other/test_x.py::t"])
