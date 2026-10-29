"""Declare the Core test set (held-out later tasks) first, then the earlier collection tasks.

Test set: the general split's 18 sqlglot tasks plus ADDED, and the later Django tasks of
SWE-Bench-CL. Each test task carries its plain-Glimmer solve-rate estimate and that estimate's
source. Collection: KNOWN_PASS sqlglot tasks, then smallest single-file sqlglot tasks by date,
never a test task. A test task that turns up in the collection list raises.
Usage: uv run python scripts/routeb/declare_core_sets.py --src S --split F --django D
         --plain-log L [--plain-log L ...] --out results/core-test-set.json --collect C
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from general_kinds import task_kind
from general_runs import task_rows

CAP = 75  # the Core prereg's step cap; cap-50 records are a floor for it
PREFIX = "tobymao__sqlglot-"
# The only non-split sqlglot tasks with a cap-75 plain record in the 20-60% band (3478, 1 of 2)
# and a hard bug that plain never solved (3339, 0 of 3) so the set can show gains.
ADDED = (f"{PREFIX}3478", f"{PREFIX}3339")
COLLECT_SQLGLOT = 40  # coordinator: about 40 earlier sqlglot tasks
EASY_STRATA = ("dialects", "expressions", "parser")


class OverlapError(ValueError):
    """A test task is also listed for collection."""


def plain_records(logs: Sequence[Path]) -> dict[str, dict[int, list[int]]]:
    """Per task, [solved, runs] by step cap, from plain-arm records only."""
    found: dict[str, dict[int, list[int]]] = {}
    for log in logs:
        for line in log.read_text().splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("resolved") is None or row.get("arm") not in (None, "plain"):
                continue
            cell = found.setdefault(row["instance_id"], {50: [0, 0], 75: [0, 0]})
            cell.setdefault(int(row["step_limit"]), [0, 0])
            cell[int(row["step_limit"])][0] += bool(row["resolved"])
            cell[int(row["step_limit"])][1] += 1
    return found


def estimate(record: dict[int, list[int]] | None) -> tuple[float | None, str]:
    """Plain solve-rate estimate at CAP and where it comes from."""
    record = record or {}
    for cap, source in ((CAP, "plain runs at cap 75"), (50, "plain runs at cap 50 (a floor)")):
        solved, runs = record.get(cap, [0, 0])
        if runs:
            return round(solved / runs, 2), f"{source}: {solved} of {runs}"
    return None, "unmeasured"


def sqlglot_entry(task: str, source: str, row: dict, record) -> dict:
    """One sqlglot test task."""
    rate, basis = estimate(record)
    kind, _ = task_kind(row["problem_statement"], row["patch"])
    return {
        "task": task,
        "repo": "sqlglot",
        "kind": str(kind),
        "source": source,
        "plain_estimate": rate,
        "estimate_source": basis,
    }


def django_entry(task: dict) -> dict:
    """One later Django test task; no plain Glimmer run exists yet."""
    return {
        "task": task["instance_id"],
        "repo": "django",
        "kind": task["task_type"],
        "source": f"SWE-Bench-CL Django later, position {task['cl_position']}",
        "plain_estimate": None,
        "estimate_source": "unmeasured; SWE-bench difficulty label " + task["difficulty"],
    }


def _ever_solved(record: dict[int, list[int]]) -> bool:
    return any(solved for solved, _ in record.values())


def _known_hard(record: dict[int, list[int]]) -> bool:
    """Two or more plain runs at the cap and never solved: collection would waste its runs."""
    return record.get(CAP, [0, 0])[1] >= 2 and not _ever_solved(record)


def collect_sqlglot(pool: list[dict], test: set[str], records, rows) -> list[str]:
    """Tasks plain Glimmer ever solved first, then small easy-stratum tasks by date."""
    known = sorted(t for t, r in records.items() if t not in test and _ever_solved(r))
    skip = test | set(known) | {t for t, r in records.items() if _known_hard(r)}
    rest = [p for p in pool if p["instance_id"] not in skip and p["subsystem"] in EASY_STRATA]
    rest.sort(
        key=lambda task: (int(task["gold_changed_lines"]), rows[task["instance_id"]]["created_at"])
    )
    return (known + [p["instance_id"] for p in rest])[:COLLECT_SQLGLOT]


def declare(args: argparse.Namespace) -> tuple[dict, list[str]]:
    """The test-set document and the sqlglot collection ids."""
    rows = task_rows(args.src / "data" / "sqlglot_rows.json")
    pool = json.loads((args.src / "data" / "pool.json").read_text())["pool"]
    records = plain_records(args.plain_log)
    split = [e["task"] for e in json.loads(args.split.read_text())["evaluation"]]
    django = json.loads(args.django.read_text())["tasks"]
    test = [sqlglot_entry(t, "general split", rows[t], records.get(t)) for t in split]
    test += [sqlglot_entry(t, "added, core", rows[t], records.get(t)) for t in ADDED]
    test += [django_entry(t) for t in django if t["phase"] == "later"]
    held = {entry["task"] for entry in test}
    collect = collect_sqlglot(pool, held, records, rows)
    collect_django = [t["instance_id"] for t in django if t["phase"] == "history"]
    if held & (set(collect) | set(collect_django)):
        raise OverlapError(f"test tasks listed for collection: {sorted(held & set(collect))}")
    measured = [e["plain_estimate"] for e in test if e["plain_estimate"] is not None]
    document = {
        "label": "exploratory DRAFT: Core test set (later, held out) and earlier collection tasks",
        "rule": "test = general split 18 + 2 added sqlglot + SWE-Bench-CL Django later 25; "
        "collect = sqlglot with any plain solve, then smallest easy-stratum tasks by date",
        "step_cap": CAP,
        "test_counts": {
            "sqlglot": len(split) + len(ADDED),
            "django": len(test) - len(split) - len(ADDED),
        },
        "sqlglot_mean_plain_estimate": round(sum(measured) / len(measured), 2),
        "test": test,
        "collect": {"sqlglot": collect, "django": collect_django},
    }
    return document, collect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--src", "--split", "--django", "--out", "--collect"):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--plain-log", type=Path, action="append", required=True)
    args = parser.parse_args()
    document, collect = declare(args)
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    args.collect.write_text("".join(json.dumps({"instance_id": t}) + "\n" for t in collect))
    print(json.dumps({k: document[k] for k in ("test_counts", "sqlglot_mean_plain_estimate")}))


if __name__ == "__main__":
    main()
