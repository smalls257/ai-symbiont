"""The held-out split for the general-lessons pilot, on hand-written rows and runs."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"
FEATURE_PATCH = """diff --git a/sqlglot/dialects/mysql.py b/sqlglot/dialects/mysql.py
--- a/sqlglot/dialects/mysql.py
+++ b/sqlglot/dialects/mysql.py
@@ -10,2 +10,3 @@ class MySQL(Dialect):
             "BIT": TokenType.BIT,
+            "SERIAL": TokenType.SERIAL,
diff --git a/tests/dialects/test_mysql.py b/tests/dialects/test_mysql.py
--- a/tests/dialects/test_mysql.py
+++ b/tests/dialects/test_mysql.py
@@ -1,1 +1,2 @@
-        x = 1
+        self.validate_identity("CREATE TABLE t (id SERIAL)")
"""
CORRECTIVE_PATCH = """diff --git a/sqlglot/parser.py b/sqlglot/parser.py
--- a/sqlglot/parser.py
+++ b/sqlglot/parser.py
@@ -5,1 +5,1 @@ class Parser:
-        if self._curr:
+        if self._curr and self._next:
"""


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


@pytest.mark.parametrize(
    ("statement", "patch", "kind", "reason"),
    [
        ("Support BYTEINT in Snowflake", CORRECTIVE_PATCH, "feature", "request-title"),
        ("[DuckDB] add support for X", CORRECTIVE_PATCH, "feature", "request-title"),
        (
            "X\n\nIs your feature request related to a problem?",
            CORRECTIVE_PATCH,
            "feature",
            "feature-template",
        ),
        ("SERIAL is not supported, raises error", FEATURE_PATCH, "bug", "bug-title"),
        (
            "SERIAL keyword is not supported in mysql",
            CORRECTIVE_PATCH,
            "feature",
            "unsupported-title",
        ),
        ("Redshift DECODE", FEATURE_PATCH, "feature", "additive-patch"),
        ("Redshift DECODE", CORRECTIVE_PATCH, "bug", "corrective-patch"),
    ],
)
def test_kind_rule_steps_in_order(monkeypatch, statement, patch, kind, reason):
    kinds = load(monkeypatch, "general_kinds")
    found = kinds.task_kind(statement, patch)
    assert (str(found[0]), str(found[1])) == (kind, reason)


def test_patch_shape_ignores_tests_and_counts_entries(monkeypatch):
    kinds = load(monkeypatch, "general_kinds")
    shape = kinds.patch_shape(FEATURE_PATCH)
    assert (shape.added, shape.removed, shape.entries, shape.definitions) == (1, 0, 1, 0)
    assert shape.is_additive()
    assert not kinds.patch_shape(CORRECTIVE_PATCH).is_additive()


def _write_split(path, tasks):
    path.write_text(json.dumps({"evaluation": [{"task": task} for task in tasks]}))


def test_evaluation_ids_read_the_committed_file(monkeypatch, tmp_path):
    split = load(monkeypatch, "general_split")
    _write_split(tmp_path / "s.json", ["a", "b"])
    assert split.evaluation_ids(tmp_path / "s.json") == {"a", "b"}


def test_evaluation_ids_refuse_a_missing_or_empty_split(monkeypatch, tmp_path):
    split = load(monkeypatch, "general_split")
    with pytest.raises(split.SplitError, match="declare the split"):
        split.evaluation_ids(tmp_path / "none.json")
    _write_split(tmp_path / "empty.json", [])
    with pytest.raises(split.SplitError, match="no evaluation tasks"):
        split.evaluation_ids(tmp_path / "empty.json")


def test_declared_split_is_ten_bugs_and_eight_features_without_repeats(monkeypatch):
    split = load(monkeypatch, "general_split")
    tasks = [entry.task for entry in split.SPLIT]
    kinds = [str(entry.kind) for entry in split.SPLIT]
    assert len(set(tasks)) == len(tasks) == 18
    assert (kinds.count("bug"), kinds.count("feature")) == (10, 8)


def _trajectory(commands):
    messages = []
    for command, code in commands:
        messages.append({"role": "assistant", "extra": {"actions": [{"command": command}]}})
        messages.append({"role": "tool", "content": "", "extra": {"returncode": code}})
    return {"messages": messages}


def _src(tmp_path, runs):
    """A plain log with one task's runs: (step_limit, resolved, commands)."""
    log = tmp_path / "runs"
    (log / "traj" / "t-1").mkdir(parents=True)
    lines = []
    for number, (cap, resolved, commands) in enumerate(runs, start=1):
        row = {
            "instance_id": "t-1",
            "stage": "screen",
            "run": number,
            "reasoning": "low",
            "step_limit": cap,
            "resolved": resolved,
            "exit_status": "x",
            "steps": 3,
        }
        lines.append(json.dumps(row))
        name = f"screen-run{number}-low.traj.json"
        (log / "traj" / "t-1" / name).write_text(json.dumps(_trajectory(commands)))
    (log / "calibration.jsonl").write_text("\n".join(lines) + "\n")
    for other in ("runs-wide", "runs-cal2", "runs-tier2"):
        (tmp_path / other).mkdir()
        (tmp_path / other / "calibration.jsonl").write_text("")
    return tmp_path


EDIT = ("sed -i 's/a/b/' sqlglot/parser.py", 0)
READ = ("cat sqlglot/parser.py", 0)


def test_plain_runs_read_facts_and_refuse_a_missing_trajectory(monkeypatch, tmp_path):
    runs = load(monkeypatch, "general_runs")
    src = _src(tmp_path, [(50, False, [READ, EDIT])])
    (found,) = list(runs.plain_runs(src))
    assert (found.step_limit, found.facts.first_edit, found.facts.edited) == (
        50,
        2,
        ("sqlglot/parser.py",),
    )
    (src / "runs" / "traj" / "t-1" / "screen-run1-low.traj.json").unlink()
    with pytest.raises(FileNotFoundError, match="without a trajectory"):
        list(runs.plain_runs(src))


@pytest.mark.parametrize(
    ("runs", "pick"),
    [
        ([(50, True, []), (50, False, []), (50, False, [])], "plain solved 1 of 3 at cap 50"),
        ([(50, True, []), (50, True, []), (50, False, [])], "plain solved 2 of 3 at cap 50"),
        ([(50, False, [EDIT])], "plain never solved, edited a source file"),
        ([(50, False, [READ])], "plain never solved, no source edit"),
        (
            [(50, False, []), (75, True, []), (75, False, [])],
            "plain unsolved at cap 50, solved 1 of 2 at cap 75",
        ),
        ([(50, True, [])], None),
    ],
)
def test_observed_pick_follows_the_record(monkeypatch, tmp_path, runs, pick):
    declare = load(monkeypatch, "declare_general_split")
    general_runs = sys.modules["general_runs"]
    found = declare.observed_pick(list(general_runs.plain_runs(_src(tmp_path, runs))))
    assert (str(found) if found else None) == pick


def test_checked_entry_refuses_a_wrong_kind_or_pick(monkeypatch, tmp_path):
    declare = load(monkeypatch, "declare_general_split")
    split, kinds = sys.modules["general_split"], sys.modules["general_kinds"]
    runs = list(sys.modules["general_runs"].plain_runs(_src(tmp_path, [(50, False, [EDIT])])))
    row = {"problem_statement": "Support SERIAL", "patch": FEATURE_PATCH}
    pool = {"subsystem": "dialects", "size_band": "S", "gold_changed_lines": "1"}
    good = split.EvalTask("t-1", kinds.TaskKind.FEATURE, split.Pick.EDITED_UNSOLVED)
    entry = declare.checked_entry(good, row, runs, pool)
    assert (entry["kind"], entry["plain_cap50"], entry["plain_cap75"]) == (
        "feature",
        [0, 1],
        [0, 0],
    )
    with pytest.raises(split.SplitError, match="the rule says feature"):
        declare.checked_entry(split.EvalTask("t-1", kinds.TaskKind.BUG, good.pick), row, runs, pool)
    wrong_pick = split.EvalTask("t-1", good.kind, split.Pick.IN_BAND)
    with pytest.raises(split.SplitError, match="record disagrees"):
        declare.checked_entry(wrong_pick, row, runs, pool)
