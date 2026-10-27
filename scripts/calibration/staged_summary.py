"""The summary file of the staged calibration driver, built from plain records.

Violation prevented: **Black Box** for the night-long run. The summary is what the laptop reads to
see how far the driver got, so how a task lands in "in_band", "history" or "pending" is a named,
tested function here rather than a branch inside the driver. No task or trajectory text is kept.

Deployed next to staged.py: staged.py imports this module as a sibling, like run_calibration.
"""

RUN_FIELDS = (
    "stage",
    "run",
    "reasoning",
    "step_limit",
    "wall_limit_s",
    "attempt",
    "exit_status",
    "steps",
    "resolved",
    "submitted",
    "patch_applied",
    "f2p",
    "p2p",
    "prompt_tokens",
    "completion_tokens",
    "prepare_s",
    "agent_s",
    "grade_s",
    "wall_s",
    "error_kind",
)
BANDS = ("in_band", "history", "pending")
RUNS_PER_TASK = 3


def band_of(chosen: str | None, graded: list[dict]) -> str:
    """Where a task stands, from its graded runs with the chosen setting.

    "pending" until the screen run and all RUNS_PER_TASK runs are graded; a task that the screen
    did not solve is "history"; solved 1 or 2 of 3 is "in_band", solved all 3 is "history".
    """
    if not chosen or not any(rec["run"] == 1 for rec in graded):
        return "pending"
    if not any(rec["run"] == 1 and rec["resolved"] for rec in graded):
        return "history"
    if len({rec["run"] for rec in graded}) < RUNS_PER_TASK:
        return "pending"
    solved = sum(rec["resolved"] for rec in graded)
    return "in_band" if solved < RUNS_PER_TASK else "history"


def task_entry(instance_id: str, runs: list[dict], chosen: str | None) -> dict:
    """One task's line: counts with the chosen setting, its band, and every run's kept fields."""
    graded = (
        [rec for rec in runs if rec["reasoning"] == chosen and rec["resolved"] is not None]
        if chosen
        else []
    )
    return {
        "instance_id": instance_id,
        "solved_with_setting": sum(rec["resolved"] for rec in graded),
        "graded_with_setting": len(graded),
        "band": band_of(chosen, graded),
        "runs": [{field: rec.get(field) for field in RUN_FIELDS} for rec in runs],
    }


def task_entries(screen: list[str], records: list[dict], chosen: str | None) -> list[dict]:
    """Entries for the screened tasks that have at least one run, in screen order."""
    entries = []
    for instance_id in screen:
        runs = [rec for rec in records if rec["instance_id"] == instance_id]
        if runs:
            entries.append(task_entry(instance_id, runs, chosen))
    return entries


def run_totals(records: list[dict]) -> dict:
    """Run counts and wall-clock totals over every record."""
    walls = [rec["wall_s"] for rec in records if rec.get("wall_s")]
    return {
        "n_runs": len(records),
        "total_hours": round(sum(walls) / 3600, 2),
        "mean_wall_s": round(sum(walls) / len(walls), 1) if walls else None,
        "ungraded_runs": sum(rec["resolved"] is None for rec in records),
    }


def build_summary(header: dict, state: dict, screen: list[str], records: list[dict]) -> dict:
    """The whole summary: static header, driver state, totals, band counts and per-task lines."""
    tasks = task_entries(screen, records, state["setting"])
    return {
        **header,
        **state,
        **run_totals(records),
        "band_counts": {band: sum(task["band"] == band for task in tasks) for band in BANDS},
        "screen_ids": screen,
        "tasks": tasks,
    }
