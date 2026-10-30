"""Core D2 test plan: seeds, task order, back-to-back runs, cutoff and the paired bootstrap.

Pure. Every number the prereg fixes is a constant here with its source, so a changed value is a
visible diff, and callers pass the time in so the plan needs no clock.
"""

import hashlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

SEED_PREFIX = (
    "core2-d2"  # prereg "Sampling": seed = first 8 hex digits of sha256(core2-d2:<id>:<arm>:<run>)
)
ORDER_PREFIX = (
    "core-d2-order"  # prereg "Order": tasks run in the order of sha256(core-d2-order:<id>)
)
SELECT_PREFIX = "core-d2"  # prereg test selection: fixed hash order, also the order W is cut from
BOOTSTRAP_SEED = 20261101  # prereg "Interval": percentile bootstrap seed
BOOTSTRAP_RESAMPLES = 10_000
CUTOFF = datetime(2026, 11, 1, 18, 0, tzinfo=ZoneInfo("America/Los_Angeles"))  # prereg cutoff
TEMPERATURE = 0.6  # prereg item 3: temperature 0 repeats byte for byte, so the arms sample
W_TASKS = 50  # prereg W: worked examples on the first 50 tasks in SELECT order


class Arm(StrEnum):
    """P plain, A the Core adapter, C the control adapter, W plain with worked examples."""

    P = "P"
    A = "A"
    C = "C"
    W = "W"


RUNS_PER_ARM = {Arm.P: 2, Arm.A: 2, Arm.C: 2, Arm.W: 1}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def run_seed(instance_id: str, arm: Arm, run: int) -> int:
    """The sampling seed of one run: first 8 hex digits of sha256(core2-d2:<id>:<arm>:<run>)."""
    return int(_sha(f"{SEED_PREFIX}:{instance_id}:{arm}:{run}")[:8], 16)


def task_order(instance_ids: Sequence[str]) -> list[str]:
    """Tasks in the seeded random order they run in."""
    return sorted(instance_ids, key=lambda task: _sha(f"{ORDER_PREFIX}:{task}"))


def worked_example_tasks(test_ids: Sequence[str]) -> frozenset[str]:
    """The first 50 tasks in the fixed selection hash order: W's tasks, whatever the run order."""
    return frozenset(sorted(test_ids, key=lambda task: _sha(f"{SELECT_PREFIX}:{task}"))[:W_TASKS])


def runs_of_task(
    instance_id: str, *, in_w: bool, arms: frozenset[Arm] = frozenset(Arm)
) -> list[tuple[Arm, int]]:
    """A task's (arm, run) pairs in the order they run back to back; W only on W tasks."""
    pairs = [
        (arm, run)
        for arm, count in RUNS_PER_ARM.items()
        for run in range(1, count + 1)
        if arm in arms and (arm is not Arm.W or in_w)
    ]
    return sorted(pairs, key=lambda pair: _sha(f"{ORDER_PREFIX}:{instance_id}:{pair[0]}:{pair[1]}"))


def may_start_task(now: datetime) -> bool:
    """True before the cutoff; a task that started earlier finishes all its runs."""
    return now < CUTOFF


def complete_tasks(
    records: Sequence[dict], test_ids: Sequence[str], arms: frozenset[Arm] = frozenset(Arm)
) -> list[str]:
    """Tasks whose every planned run has a graded record (none void, none missing)."""
    graded: dict[str, set[tuple[str, int]]] = {}
    for rec in records:
        if rec.get("resolved") is not None:
            graded.setdefault(rec["instance_id"], set()).add((rec["arm"], rec["run"]))
    worked = worked_example_tasks(test_ids)
    complete = []
    for task in test_ids:
        planned = {
            (str(arm), run) for arm, run in runs_of_task(task, in_w=task in worked, arms=arms)
        }
        if graded.get(task, set()) >= planned:
            complete.append(task)
    return complete


def task_means(records: Sequence[dict], tasks: Sequence[str], arm: Arm) -> dict[str, float]:
    """Per task, the mean of the arm's graded runs (resolved as 0 or 1)."""
    found: dict[str, list[float]] = {}
    for rec in records:
        if (
            rec["arm"] == str(arm)
            and rec["instance_id"] in tasks
            and rec.get("resolved") is not None
        ):
            found.setdefault(rec["instance_id"], []).append(float(rec["resolved"]))
    return {task: sum(runs) / len(runs) for task, runs in found.items()}


def bootstrap_ci(
    diffs: Sequence[float], rng: random.Random | None = None
) -> tuple[float, float, float]:
    """(mean, 2.5th, 97.5th percentile) over tasks; 10,000 resamples at the prereg seed."""
    rng = rng or random.Random(BOOTSTRAP_SEED)
    count = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=count)) / count for _ in range(BOOTSTRAP_RESAMPLES))
    low, high = means[int(0.025 * BOOTSTRAP_RESAMPLES)], means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
    return sum(diffs) / count, low, high


def paired_differences(
    records: Sequence[dict], tasks: Sequence[str], arm: Arm, reference: Arm
) -> list[float]:
    """d = (arm's mean) - (reference's mean) per analyzed task that has both."""
    first, second = task_means(records, tasks, arm), task_means(records, tasks, reference)
    return [first[t] - second[t] for t in tasks if t in first and t in second]


def co_primaries(
    records: Sequence[dict], test_ids: Sequence[str], arms: frozenset[Arm] = frozenset(Arm)
) -> dict[str, tuple[float, float, float]]:
    """A minus P and A minus C over the complete tasks, each with its bootstrap interval."""
    tasks = complete_tasks(records, test_ids, arms)
    return {
        f"A-{ref}": bootstrap_ci(paired_differences(records, tasks, Arm.A, ref))
        for ref in (Arm.P, Arm.C)
    }


def claim_holds(result: dict[str, tuple[float, float, float]]) -> bool:
    """The headline needs BOTH lower bounds above 0."""
    return all(low > 0 for _, low, _ in result.values())


EARLY_STOP_TASKS = 50  # prereg: the check runs on the first 50 complete tasks in run order


def first_complete(
    records: Sequence[dict], test_ids: Sequence[str], arms: frozenset[Arm] = frozenset(Arm)
) -> list[str]:
    """The first EARLY_STOP_TASKS complete tasks in RUN order (the seeded task order)."""
    complete = set(complete_tasks(records, test_ids, arms))
    return [task for task in task_order(test_ids) if task in complete][:EARLY_STOP_TASKS]


def early_stop_due(records: Sequence[dict], test_ids: Sequence[str], arms: frozenset[Arm]) -> bool:
    """True once 50 tasks are complete and A minus P over them lies wholly below 0."""
    first = first_complete(records, test_ids, arms)
    if len(first) < EARLY_STOP_TASKS:
        return False
    result = bootstrap_ci(paired_differences(records, first, Arm.A, Arm.P))
    return stops_early(result, planned=2 * EARLY_STOP_TASKS, complete=len(first))


def stops_early(result: tuple[float, float, float], planned: int, complete: int) -> bool:
    """Early stop: at half the planned tasks, only if A minus P's interval lies wholly below 0."""
    return complete >= planned // 2 and result[2] < 0


@dataclass(frozen=True)
class RunSpec:
    """One run to execute: the task, the arm, the run number and its sampling seed."""

    task: str
    arm: Arm
    run: int
    seed: int


def spec_of(task: str, arm: Arm, run: int) -> RunSpec:
    return RunSpec(task, arm, run, run_seed(task, arm, run))


Executor = Callable[[RunSpec], dict]  # one run -> its record (resolved None = void)
