"""How the screen picks its tasks: the smallest gold patches, or a seeded spread over strata."""

import random
from enum import StrEnum

SCREEN_N = 40
# Fixed so a restarted driver rebuilds the same screen; the resume log is keyed by instance id.
STRATIFIED_SEED = 20261027


class ScreenRule(StrEnum):
    SMALLEST = "smallest"
    STRATIFIED = "stratified"


class UnlabeledPoolError(ValueError):
    """A pool entry has no subsystem/size_band: run label_pool.py on the workdir first."""


def smallest_screen(pool: list[dict], count: int = SCREEN_N) -> list[str]:
    """The `count` tasks with the fewest changed gold lines, ties by instance_id."""
    ordered = sorted(pool, key=lambda item: (item["gold_changed_lines"], item["instance_id"]))
    return [entry["instance_id"] for entry in ordered[:count]]


def cells_of(pool: list[dict]) -> dict[str, list[str]]:
    """Instance ids per "subsystem/size_band" cell, ids sorted; raises if a label is missing."""
    cells: dict[str, list[str]] = {}
    for entry in pool:
        if "subsystem" not in entry or "size_band" not in entry:
            raise UnlabeledPoolError(f"{entry['instance_id']} has no strata labels")
        cells.setdefault(f"{entry['subsystem']}/{entry['size_band']}", []).append(
            entry["instance_id"]
        )
    return {cell: sorted(ids) for cell, ids in sorted(cells.items())}


def stratified_screen(
    pool: list[dict], excluded: set[str], seed: int = STRATIFIED_SEED, count: int = SCREEN_N
) -> list[str]:
    """Up to `count` ids, round-robin over non-empty cells; `excluded` (already run) is dropped.

    Seeded, so the same pool, exclusions and seed give the same list. Pick order matters: any
    prefix (the checkpoint's first 10) already mixes cells.
    """
    cells = cells_of([entry for entry in pool if entry["instance_id"] not in excluded])
    rng = random.Random(seed)
    queues = {cell: rng.sample(ids, len(ids)) for cell, ids in cells.items()}
    order = rng.sample(sorted(queues), len(queues))
    picked: list[str] = []
    while len(picked) < count and any(queues.values()):
        for cell in order:
            if queues[cell] and len(picked) < count:
                picked.append(queues[cell].pop())
    return picked


def pick_counts(pool: list[dict], picked: list[str]) -> dict[str, int]:
    """Picked tasks per "subsystem/size_band" cell (counts and labels only)."""
    chosen = set(picked)
    counts: dict[str, int] = {}
    for cell, ids in cells_of(pool).items():
        if hits := sum(iid in chosen for iid in ids):
            counts[cell] = hits
    return counts


def select_screen(rule: ScreenRule, pool: list[dict], excluded: set[str]) -> list[str]:
    """The screen ids for a named rule; SMALLEST ignores `excluded` to keep today's behavior."""
    if rule is ScreenRule.SMALLEST:
        return smallest_screen(pool)
    return stratified_screen(pool, excluded)
