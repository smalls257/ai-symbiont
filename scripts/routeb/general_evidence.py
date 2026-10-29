"""Load the non-evaluation evidence for general lessons: plain runs and upstream fixes.

Every evaluation task named in the committed split is removed here, at the one door, and the
loaded evidence is checked again so a later filter bug raises instead of leaking an answer.
Gold places are resolved against the public sqlglot clone at each task's base commit.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from general_kinds import TaskKind, issue_title, task_kind
from general_places import entry_reuse
from general_runs import PlainRun, plain_runs, task_rows
from general_split import evaluation_ids
from sqlglot_evidence import places_at, source_at
from sqlglot_places import Place, diff_files


@dataclass(frozen=True)
class SourceTask:
    """One non-evaluation pool task: its kind, upstream fix places and test layout."""

    task: str
    kind: TaskKind
    title: str
    gold_files: tuple[str, ...]
    places: tuple[Place, ...]
    test_modules: tuple[str, ...]
    test_patch: str
    gold_patch: str
    places_resolved: bool  # False: a changed file is missing at the base commit; counted, not used
    entry_reuse: tuple[int, int]  # (map entries reusing an existing helper, entries calling one)


@dataclass(frozen=True)
class Evidence:
    """Everything a general lesson may be built from, and the evaluation tasks it must avoid."""

    tasks: dict[str, SourceTask]
    runs: tuple[PlainRun, ...]
    evaluation: frozenset[str]
    evaluation_patches: dict[str, str]
    evaluation_places: dict[str, tuple[Place, ...]]


class EvaluationLeakError(ValueError):
    """Evidence from an evaluation task reached the lesson builder."""


def test_modules(fail_to_pass: Sequence[str]) -> tuple[str, ...]:
    """Dotted unittest modules of the failing tests, in order."""
    modules = [re.sub(r"\.py$", "", test.split("::")[0]).replace("/", ".") for test in fail_to_pass]
    return tuple(module for module in dict.fromkeys(modules) if module.startswith("tests"))


def _existing(patch: str) -> list[str]:
    """Changed sqlglot/ python files that existed before the patch."""
    created = {line[6:] for line in patch.splitlines() if line.startswith("+++ b/")} - {
        line[6:] for line in patch.splitlines() if line.startswith("--- a/")
    }
    return [
        p
        for p in diff_files(patch)
        if p.startswith("sqlglot/") and p.endswith(".py") and p not in created
    ]


def source_task(row: dict, clone: Path) -> SourceTask:
    """A pool task's upstream evidence; places stay empty, flagged, when git lacks a file."""
    kind, _ = task_kind(row["problem_statement"], row["patch"])
    gold_files = [path for path in diff_files(row["patch"]) if path.startswith("sqlglot/")]
    try:
        found = places_at(row["patch"], clone, row["base_commit"])
        sources = {p: source_at(clone, row["base_commit"], p) for p in _existing(row["patch"])}
    except FileNotFoundError:
        found, sources = None, {}
    return SourceTask(
        task=row["instance_id"],
        kind=kind,
        title=issue_title(row["problem_statement"]),
        gold_files=tuple(gold_files),
        places=found or (),
        test_modules=test_modules(row["FAIL_TO_PASS"]),
        test_patch=row["test_patch"],
        gold_patch=row["patch"],
        places_resolved=found is not None,
        entry_reuse=entry_reuse(row["patch"], sources),
    )


def refuse_evaluation(evidence: Evidence) -> Evidence:
    """Return the evidence, or raise if any task or run belongs to the evaluation split."""
    leaked = sorted(set(evidence.tasks) & evidence.evaluation)
    leaked += sorted({run.task for run in evidence.runs} & evidence.evaluation)
    if leaked:
        raise EvaluationLeakError(f"evaluation tasks in lesson evidence: {leaked}")
    return evidence


def load_evidence(src: Path, split: Path, clone: Path) -> Evidence:
    """Non-evaluation pool tasks and plain runs under `src`; eval ids come from `split`."""
    held = evaluation_ids(split)
    rows = task_rows(src / "data" / "sqlglot_rows.json")
    pool = [
        entry["instance_id"] for entry in json.loads((src / "data/pool.json").read_text())["pool"]
    ]
    return refuse_evaluation(
        Evidence(
            tasks={task: source_task(rows[task], clone) for task in pool if task not in held},
            runs=tuple(run for run in plain_runs(src) if run.task not in held),
            evaluation=held,
            evaluation_patches={task: rows[task]["patch"] for task in sorted(held)},
            evaluation_places={
                task: places_at(rows[task]["patch"], clone, rows[task]["base_commit"])
                for task in sorted(held)
            },
        )
    )
