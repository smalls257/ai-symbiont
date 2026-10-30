"""Core D2 test runner: every arm of a task back to back, on ONE server, to the cutoff.

Several of these processes run at once, one per server slot, and take tasks from a shared seeded
order through a claim log. A void run is rerun and never scored; a task that stays void on a
healthy server is dropped and reported; a server that stops answering gives its task back whole
(the block's records are voided) so another server runs all its arms. Resumes from <out>.
Usage: python core2_test_run.py --test-set T --rows R --config C --out DIR --server NAME --worker N
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from core2_test_claims import ClaimBook
from core2_test_plan import (
    TEMPERATURE,
    Arm,
    Executor,
    early_stop_due,
    may_start_task,
    run_seed,
    runs_of_task,
    spec_of,
    task_order,
    worked_example_tasks,
)

VOID_RERUNS = (
    2  # prereg: a void run is rerun up to twice; still void on a healthy server -> dropped
)
RECHECK_S = 300  # a server that stopped answering is probed again after this long


class ArmNotBuiltError(NotImplementedError):
    """The arm has no executor yet (W: worked examples). Raised, never run as plain."""


class Outcome(StrEnum):
    FINISHED = "finished"
    DROPPED = "dropped"  # stayed void on a healthy server
    SERVER_DOWN = "server_down"  # the server stopped answering: give the task back


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
    """What one runner process shares: executor, record directory, arms, clock, server identity."""

    executor: Executor
    out: Path
    arms: frozenset[Arm]
    now: Callable[[], datetime]
    server: str
    worker: int = 1
    healthy: Callable[[], bool] = lambda: True
    guard: Callable[[], str | None] = lambda: None  # the arm whose probe failed, else None
    wait: Callable[[float], None] = time.sleep
    limit: int | None = None

    @property
    def who(self) -> str:
        return f"{self.server}-{self.worker}"


def graded_runs(out: Path) -> list[dict]:
    """Records of blocks that were not voided (a returned task's block is never scored)."""
    voided = {row["block"] for row in read_jsonl(out / "voided_blocks.jsonl")}
    return [row for row in read_jsonl(out / "runs.jsonl") if row.get("block") not in voided]


def void_block(phase: Phase, task: str, block: str, reason: str) -> None:
    row = {"task": task, "block": block, "server": phase.server, "reason": reason}
    append_jsonl(phase.out / "voided_blocks.jsonl", row)


def effective_arms(phase: Phase, test_ids: list[str]) -> frozenset[Arm]:
    """The arms new tasks run: A is dropped for good once the early-stop check fires."""
    marker = phase.out / "early_stop.json"
    if Arm.A in phase.arms and not marker.is_file():
        records = graded_runs(phase.out)
        if early_stop_due(records, test_ids, phase.arms):
            marker.write_text(json.dumps({"rule": "A minus P wholly below 0 at 50 complete tasks"}))
    return phase.arms - {Arm.A} if marker.is_file() else phase.arms


def run_task_block(phase: Phase, task: str, block: str, *, in_w: bool) -> Outcome:
    """Every planned run of one task on this server, recorded with the server and block."""
    for arm, run in runs_of_task(task, in_w=in_w, arms=phase.arms):
        spec = spec_of(task, arm, run)
        rec, voids = run_until_graded(lambda spec=spec: phase.executor(spec), VOID_RERUNS)
        meta = {"instance_id": task, "arm": str(arm), "run": run, "seed": spec.seed,
                "server": phase.server, "block": block}  # fmt: skip
        for void in voids:
            append_jsonl(phase.out / "voids.jsonl", void | meta)
        if rec is None:
            if not phase.healthy():
                return Outcome.SERVER_DOWN
            reason = voids[-1].get("error_kind") or "ungraded"
            append_jsonl(phase.out / "dropped.jsonl", meta | {"reason": reason})
            return Outcome.DROPPED
        append_jsonl(phase.out / "runs.jsonl", rec | meta | {"temperature": TEMPERATURE})
    return Outcome.FINISHED


def release_stale(phase: Phase, book: ClaimBook) -> int:
    """Void and release blocks this worker started before it died; returns how many."""
    stale = book.stale_blocks(phase.who)
    for task, block in stale:
        void_block(phase, task, block, "worker restarted mid-task")
        book.release(task, block, phase.who)
    return len(stale)


def run_phase(test_ids: list[str], phase: Phase) -> dict:
    """Claim tasks in seeded order until the cutoff; counts of tasks finished, dropped, returned."""
    phase.out.mkdir(parents=True, exist_ok=True)
    book = ClaimBook(phase.out / "claims.jsonl")
    counts = {
        "finished": 0,
        "dropped": 0,
        "returned": 0,
        "released_stale": release_stale(phase, book),
    }
    w_tasks, order = worked_example_tasks(test_ids), task_order(test_ids)
    started = 0
    while may_start_task(phase.now()) and (phase.limit is None or started < phase.limit):
        if not phase.healthy():
            phase.wait(RECHECK_S)
            continue
        skip = {row["instance_id"] for row in read_jsonl(phase.out / "dropped.jsonl")}
        claimed = book.claim_next(order, skip, phase.who)
        if claimed is None:
            break
        task, block = claimed
        bad_arm = phase.guard()
        if bad_arm is not None:  # an adapter state we did not choose: no run on this server
            void_block(phase, task, block, f"probe failed for arm {bad_arm}")
            book.release(task, block, phase.who)
            (phase.out / f"stopped-{phase.server}.json").write_text(json.dumps({"arm": bad_arm}))
            counts["stopped_arm"] = bad_arm
            break
        started += 1
        block_phase = replace(phase, arms=effective_arms(phase, test_ids))
        outcome = run_task_block(block_phase, task, block, in_w=task in w_tasks)
        if outcome is Outcome.SERVER_DOWN:
            void_block(phase, task, block, "server stopped answering")
            book.release(task, block, phase.who)
            counts["returned"] += 1
            continue
        book.finish(task, block, phase.who)
        counts["finished" if outcome is Outcome.FINISHED else "dropped"] += 1
    return counts


def dry_plan(test_ids: list[str], arms: frozenset[Arm], limit: int) -> list[dict]:
    """What would run for the first `limit` tasks: arm, run, seed. No call is made."""
    w_tasks = worked_example_tasks(test_ids)
    plan = []
    for task in task_order(test_ids)[:limit]:
        for arm, run in runs_of_task(task, in_w=task in w_tasks, arms=arms):
            seed = run_seed(task, arm, run)
            plan.append({"task": task, "arm": str(arm), "run": run, "seed": seed})
    return plan


def server_settings(config: dict, name: str) -> dict:
    """The named server's entry; KeyError lists the configured names."""
    if name not in config["servers"]:
        raise KeyError(f"server {name!r} is not configured (have {sorted(config['servers'])})")
    return config["servers"][name]


def main() -> None:
    from core2_test_executors import (  # noqa: PLC0415  heavy imports
        build_executor,
        failed_probe,
        server_probe,
    )

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--test-set", "--rows", "--config", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--worker", type=int, default=1)
    parser.add_argument("--arms", nargs="+", default=["P", "A", "C"], choices=[str(a) for a in Arm])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    test_ids = json.loads(args.test_set.read_text())["test"]
    arms = frozenset(Arm(a) for a in args.arms)
    if args.dry_run:
        print(json.dumps(dry_plan(test_ids, arms, args.limit or 1), indent=1))
        return
    config = json.loads(args.config.read_text())
    server = server_settings(config, args.server)
    os.environ["SYMBIONT_GLIMMER_URL"] = server["url"]
    executor = build_executor(server, args.rows, args.out)
    phase = Phase(executor, args.out, arms, datetime.now().astimezone, args.server, args.worker,
                  lambda: server_probe(server), guard=lambda: failed_probe(server, arms),
                  limit=args.limit)  # fmt: skip
    print(json.dumps(run_phase(test_ids, phase)))


if __name__ == "__main__":
    sys.exit(main())
