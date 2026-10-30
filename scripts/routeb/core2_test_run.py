"""Core D2 test runner: every arm of a task back to back, tasks in seeded order, to the cutoff.

A void run (infra, model_api, failed scrub) is rerun and never scored,
a task that stays void is excluded and reported, and a missing adapter is an error, not a plain
run under the adapter's name. Resumes from <out>/runs.jsonl. Prints counts and ids only.
Usage: python core2_test_run.py --test-set T --rows R --config C --out DIR [--dry-run] [--limit N]
"""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core2_test_plan import (
    TEMPERATURE,
    Arm,
    Executor,
    may_start_task,
    run_seed,
    runs_of_task,
    spec_of,
    task_order,
    worked_example_tasks,
)

VOID_RERUNS = (
    2  # prereg: a void run is rerun before the next task starts; still void -> task dropped
)


class ArmNotBuiltError(NotImplementedError):
    """The arm has no executor yet (W: worked examples). Raised, never run as plain."""


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a") as log:
        log.write(json.dumps(row) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_until_graded(once: Callable[[], dict], reruns: int) -> tuple[dict | None, list[dict]]:
    """(graded record or None, void records). Void = resolved None: rerun up to `reruns` times."""
    voids: list[dict] = []
    for _ in range(reruns + 1):
        rec = once()
        if rec.get("resolved") is not None:
            return rec, voids
        voids.append(rec)
    return None, voids


@dataclass(frozen=True)
class Phase:
    """What the whole test shares: the executor, the record directory, the arms, the clock."""

    executor: Executor
    out: Path
    arms: frozenset[Arm]
    now: Callable[[], datetime]
    limit: int | None = None


def run_task_block(phase: Phase, task: str, done: set, *, in_w: bool) -> bool:
    """Every planned run of one task. False when a run stayed void: the task is dropped."""
    for arm, run in runs_of_task(task, in_w=in_w, arms=phase.arms):
        if (task, str(arm), run) in done:
            continue
        spec = spec_of(task, arm, run)
        rec, voids = run_until_graded(lambda spec=spec: phase.executor(spec), VOID_RERUNS)
        meta = {"instance_id": task, "arm": str(arm), "run": run, "seed": spec.seed}
        for void in voids:
            append_jsonl(phase.out / "voids.jsonl", void | meta)
        if rec is None:
            reason = voids[-1].get("error_kind") or "ungraded"
            append_jsonl(phase.out / "dropped.jsonl", meta | {"reason": reason})
            return False
        append_jsonl(phase.out / "runs.jsonl", rec | meta | {"temperature": TEMPERATURE})
    return True


def run_phase(test_ids: list[str], phase: Phase) -> dict:
    """Tasks in seeded order until the cutoff. Counts of tasks started, finished and dropped."""
    phase.out.mkdir(parents=True, exist_ok=True)
    done = {(r["instance_id"], r["arm"], r["run"]) for r in read_jsonl(phase.out / "runs.jsonl")}
    dropped = {r["instance_id"] for r in read_jsonl(phase.out / "dropped.jsonl")}
    w_tasks = worked_example_tasks(test_ids)
    started = finished = 0
    for task in task_order(test_ids):
        if task in dropped:
            continue
        if not may_start_task(phase.now()) or (phase.limit is not None and started >= phase.limit):
            break
        started += 1
        finished += run_task_block(phase, task, done, in_w=task in w_tasks)
    return {"started": started, "finished": finished, "dropped": started - finished}


def dry_plan(test_ids: list[str], arms: frozenset[Arm], limit: int) -> list[dict]:
    """What would run for the first `limit` tasks: arm, run, seed. No call is made."""
    w_tasks = worked_example_tasks(test_ids)
    plan = []
    for task in task_order(test_ids)[:limit]:
        for arm, run in runs_of_task(task, in_w=task in w_tasks, arms=arms):
            plan.append(
                {"task": task, "arm": str(arm), "run": run, "seed": run_seed(task, arm, run)}
            )
    return plan


def main() -> None:
    from core2_test_executors import build_executor  # noqa: PLC0415  heavy imports only for real runs

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", default=["P", "A", "C"], choices=[str(a) for a in Arm])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    test_ids = json.loads(args.test_set.read_text())["test"]
    arms = frozenset(Arm(a) for a in args.arms)
    if args.dry_run:
        print(json.dumps(dry_plan(test_ids, arms, args.limit or 1), indent=1))
        return
    executor = build_executor(json.loads(args.config.read_text()), args.rows, args.out)
    print(
        json.dumps(
            run_phase(test_ids, executor, args.out, datetime.now().astimezone, arms, args.limit)
        )
    )


if __name__ == "__main__":
    sys.exit(main())
