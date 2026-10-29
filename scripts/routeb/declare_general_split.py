"""Write the held-out split file from the declared split after checking it against the data.

A declared kind that the kind rule disagrees with, or a pick the plain record does not show,
raises naming the task. The file holds ids, labels and counts only.
Usage: uv run python scripts/routeb/declare_general_split.py --src SRC --out FILE
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from general_kinds import RULE, task_kind
from general_runs import PlainRun, plain_runs, task_rows
from general_split import SPLIT, EvalTask, Pick, SplitError

CAP_SHORT, CAP_LONG = 50, 75  # the calibration caps (glimmer-analysis.md, cal2-report.md)


def record(runs: Sequence[PlainRun], cap: int) -> list[int]:
    """[solved, runs] at one step cap."""
    at_cap = [run for run in runs if run.step_limit == cap]
    return [sum(run.resolved for run in at_cap), len(at_cap)]


def observed_pick(runs: Sequence[PlainRun]) -> Pick | None:
    """The pick the plain record supports, or None when no pick fits."""
    short, long = record(runs, CAP_SHORT), record(runs, CAP_LONG)
    if short == [1, 3]:
        return Pick.IN_BAND
    if short == [2, 3]:
        return Pick.NEAR_BAND
    if short[0] or not short[1]:
        return None
    if long[0] and long[0] < long[1]:
        return Pick.SOLVED_AT_75
    edited = any(run.facts.first_edit for run in runs)
    return Pick.EDITED_UNSOLVED if edited else Pick.UNSOLVED_NO_EDIT


def checked_entry(declared: EvalTask, row: dict, runs: Sequence[PlainRun], pool: dict) -> dict:
    """One split entry; raises SplitError if the data disagrees with the declaration."""
    kind, reason = task_kind(row["problem_statement"], row["patch"])
    if kind is not declared.kind:
        raise SplitError(f"{declared.task}: declared {declared.kind}, the rule says {kind}")
    if observed_pick(runs) is not declared.pick:
        raise SplitError(f"{declared.task}: declared '{declared.pick}', record disagrees")
    return {
        "task": declared.task,
        "kind": str(kind),
        "kind_reason": str(reason),
        "pick": str(declared.pick),
        "stratum": pool["subsystem"],
        "size_band": pool["size_band"],
        "gold_changed_lines": int(pool["gold_changed_lines"]),
        "plain_cap50": record(runs, CAP_SHORT),
        "plain_cap75": record(runs, CAP_LONG),
    }


def pool_kinds(rows: dict[str, dict], pool_ids: Sequence[str]) -> dict[str, dict[str, int]]:
    """Kind counts over the whole task pool, by the rule step that decided them."""
    found: dict[str, Counter[str]] = {}
    for task in pool_ids:
        kind, reason = task_kind(rows[task]["problem_statement"], rows[task]["patch"])
        found.setdefault(str(kind), Counter())[str(reason)] += 1
    return {kind: dict(counts) | {"total": sum(counts.values())} for kind, counts in found.items()}


def split_document(src: Path) -> dict:
    """The split file's content."""
    rows = task_rows(src / "data" / "sqlglot_rows.json")
    pool = {
        p["instance_id"]: p for p in json.loads((src / "data" / "pool.json").read_text())["pool"]
    }
    by_task: dict[str, list[PlainRun]] = {}
    for run in plain_runs(src):
        by_task.setdefault(run.task, []).append(run)
    entries = [checked_entry(d, rows[d.task], by_task.get(d.task, []), pool[d.task]) for d in SPLIT]
    held = {entry["task"] for entry in entries}
    return {
        "label": "exploratory: held-out split for the general-lessons pilot, declared first",
        "rule": RULE,
        "note": "no run, gold patch or upstream fix of an evaluation task may feed any lesson",
        "pool_size": len(pool),
        "pool_kinds": pool_kinds(rows, list(pool)),
        "evaluation_kinds": dict(Counter(entry["kind"] for entry in entries)),
        "evaluation": entries,
        "source_tasks_with_plain_runs": sorted(set(by_task) - held),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, required=True, help="plain logs and data/ rows")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = split_document(args.src)
    args.out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: document[k] for k in ("pool_kinds", "evaluation_kinds")}, indent=1))


if __name__ == "__main__":
    main()
