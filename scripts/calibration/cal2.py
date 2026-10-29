"""CAL2: three plain-Glimmer runs per already-screened task under a higher step cap.

The 50-step screen mixed hard tasks with tasks the cap cut off; CAL2 re-measures them at a raised
cap, adaptively (priority order, sequential stopping, TARGET_IN_BAND / MIN_STRATA / BARREN_LIMIT
stop rules), keeps tasks solved 1 or 2 of 3, and resumes from its log. Summary: ids, counts, labels.
--fixed-runs/--lessons runs the lesson arm, --adapter personal Glimmer; records carry the arm.
Usage: python launch.py <workdir> --candidates-log runs/calibration.jsonl --runs-dir runs-cal2
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading
import time
from pathlib import Path

from lessons import Arm, lesson_hash, load_lessons, statement_with_lesson
from screen_rules import cells_of
from staged import BlockedError, Driver, add_limit_arguments, settings_for
from staged_summary import RUN_FIELDS, RUNS_PER_TASK, run_totals

TARGET_IN_BAND = 8  # coordinator ruling 2026-10-28 (was 15): enough in-band tasks for the pool
MIN_STRATA = 2  # spread them over this many strata, as far as the candidates allow
BARREN_LIMIT = 20  # finished tasks in a row with no new in-band task end the search
ABOVE_BAND = "above_band"
REASONING = "low"  # every earlier screen run used "low"; no medium run exists to compare with
BANDS = ("in_band", "too_easy", "too_hard", "pending")  # + ABOVE_BAND skips, counted apart


def band_of_candidate(graded_runs: list[dict]) -> str:
    """Where a candidate stands after its graded runs.

    "pending" before 2 runs. With 2 or more: no solve is too_hard, every run solved is too_easy,
    anything between is in_band (1 of 2 is in band whatever run 3 does).
    """
    count = len({rec["run"] for rec in graded_runs})
    if count < 2:
        return "pending"
    solved = sum(rec["resolved"] for rec in graded_runs)
    if solved == 0:
        return "too_hard"
    return "too_easy" if solved == count else "in_band"


def is_complete(graded_runs: list[dict]) -> bool:
    """A task has its verdict: 2 runs agree (0 or 2 solved), or all 3 runs are graded."""
    count = len({rec["run"] for rec in graded_runs})
    solved = sum(rec["resolved"] for rec in graded_runs)
    return count >= RUNS_PER_TASK or (count == 2 and solved != 1)


def prior_tier(old_runs: list[dict]) -> int | str:
    """Old-cap evidence: ABOVE_BAND, or 0 solved at least once, 1 step-limit cut-off, 2 the rest."""
    graded = [rec for rec in old_runs if rec["resolved"] is not None]
    solved = sum(rec["resolved"] for rec in graded)
    if len(graded) >= 2 and solved == len(graded):
        return ABOVE_BAND
    if solved:
        return 0
    return 1 if any(rec.get("exit_status") == "LimitsExceeded" for rec in graded) else 2


def priority_order(old_records: list[dict]) -> tuple[list[str], list[str]]:
    """(ids to measure, most informative first; ids skipped as above band at the old cap)."""
    by_task: dict[str, list[dict]] = {}
    for rec in old_records:
        by_task.setdefault(rec["instance_id"], []).append(rec)
    tiers = {iid: prior_tier(runs) for iid, runs in by_task.items()}
    skipped = sorted(iid for iid, tier in tiers.items() if tier == ABOVE_BAND)
    todo = sorted((tier, iid) for iid, tier in tiers.items() if tier != ABOVE_BAND)
    return [iid for _, iid in todo], skipped


def stop_reason(finished: list[tuple[str, str]]) -> str | None:
    """Why the search ends, from (stratum, band) of finished tasks in priority order, else None."""
    in_band = [stratum for stratum, band in finished if band == "in_band"]
    if len(in_band) >= TARGET_IN_BAND and len(set(in_band)) >= MIN_STRATA:
        return f"{len(in_band)} in band over {len(set(in_band))} strata"
    barren = 0
    for _, band in reversed(finished):
        if band == "in_band":
            break
        barren += 1
    if barren >= BARREN_LIMIT:
        return f"{barren} finished tasks in a row without a new in-band task"
    return None


def prior_records(workdir: Path, logs: list[str]) -> list[dict]:
    """Every record of the given earlier logs; raises if a log is missing."""
    return [
        json.loads(line)
        for log in logs
        for line in (workdir / log).read_text().splitlines()
        if line
    ]


def file_order(records: list[dict]) -> list[str]:
    """Distinct instance ids in the order the candidate file lists them."""
    return list(dict.fromkeys(rec["instance_id"] for rec in records))


def stratum_labels(pool: list[dict], ids: list[str]) -> dict[str, str]:
    """Instance id -> "subsystem/size_band" for the candidates; raises if one has no label."""
    wanted = set(ids)
    cells = cells_of([entry for entry in pool if entry["instance_id"] in wanted])
    labels = {iid: cell for cell, members in cells.items() for iid in members}
    missing = wanted - labels.keys()
    if missing:
        raise KeyError(f"{len(missing)} candidates are not in the pool: {sorted(missing)[:3]}")
    return labels


def candidate_entry(iid: str, stratum: str, runs: list[dict]) -> dict:
    """One task's line: stratum, graded count, solved count, band and every run's kept fields."""
    graded = [rec for rec in runs if rec["resolved"] is not None]
    return {
        "instance_id": iid,
        "stratum": stratum,
        "graded": len(graded),
        "solved": sum(rec["resolved"] for rec in graded),
        "band": band_of_candidate(graded),
        "runs": [{field: rec.get(field) for field in RUN_FIELDS} for rec in runs],
    }


def per_stratum(entries: list[dict]) -> dict[str, dict[str, int]]:
    """Band counts per stratum label."""
    table: dict[str, dict[str, int]] = {}
    for entry in entries:
        row = table.setdefault(entry["stratum"], dict.fromkeys(BANDS, 0))
        row[entry["band"]] += 1
    return dict(sorted(table.items()))


class CandidateDriver(Driver):
    """Adaptive measurement of the candidates at one setting; summary by band and stratum."""

    def __init__(self, workdir: Path, runs_dir: str, logs: list[str], fixed_runs: int = 0):
        super().__init__(workdir, runs_dir=runs_dir)
        pool = json.loads((workdir / "data/pool.json").read_text())["pool"]
        records = prior_records(workdir, logs)
        self.fixed_runs = fixed_runs  # 0 = adaptive; N = exactly N runs per listed task, no stop
        if fixed_runs:
            self.screen, self.skipped = file_order(records), []
        else:
            self.screen, self.skipped = priority_order(records)
        self.strata = stratum_labels(pool, self.screen + self.skipped)
        self.header = self.header | {
            "plan": f"CAL2 adaptive: {len(self.screen)} candidates in priority order, "
            f"{len(self.skipped)} skipped above band at the old cap; runs 1-2, run 3 only at "
            f"1 of 2; stop at {TARGET_IN_BAND} in band over {MIN_STRATA} strata "
            f"or {BARREN_LIMIT} barren",
            "candidate_logs": logs,
            "skipped_above_band": self.skipped,
        }
        self.state["stage"] = "cal2"
        self.state["setting"] = REASONING
        self.stop: str | None = None
        self._lock = threading.RLock()  # decide() and _record() both write the summary
        self.arm, self.lesson_hashes = Arm.PLAIN, {}

    def give_lessons(self, path: Path) -> None:
        """Lesson arm: each listed task's lesson goes before its statement; raises if one lacks."""
        lessons = load_lessons(path, self.screen)
        for iid, text in lessons.items():
            self.rows[iid] = statement_with_lesson(self.rows[iid], text)
        self.arm = Arm.LESSON
        self.lesson_hashes = {iid: lesson_hash(text) for iid, text in lessons.items()}
        self.header = self.header | {"arm": str(self.arm), "lesson_sha": self.lesson_hashes}

    def use_adapter(self, adapter_id: int) -> None:
        """Personal-Glimmer arm: every model call carries the LoRA; raises if lessons are set."""
        if self.arm is not Arm.PLAIN:
            raise ValueError(f"one arm per run: already {self.arm}, cannot add the adapter")
        self.low = dataclasses.replace(self.low, adapter_id=adapter_id)
        self.arm = Arm.PERSONAL_LORA
        self.header = self.header | {"arm": str(self.arm), "adapter_id": adapter_id}

    def _record(self, rec: dict) -> None:
        """Stamp the arm, the lesson hash and the adapter id on every record before it is logged."""
        stamp = {
            "arm": str(self.arm),
            "lesson_sha": self.lesson_hashes.get(rec["instance_id"]),
            "adapter_id": self.low.adapter_id,
        }
        super()._record(rec | stamp)

    def graded_runs(self, iid: str) -> list[dict]:
        """The graded records of one task under the current setting."""
        return [
            rec
            for rec in self.records
            if rec["instance_id"] == iid
            and rec["step_limit"] == self.low.step_limit
            and rec["resolved"] is not None
        ]

    def finished_tasks(self) -> list[tuple[str, str]]:
        """(stratum, band) of every task with its verdict, in priority order."""
        graded = {iid: self.graded_runs(iid) for iid in self.screen}
        return [
            (self.strata[iid], band_of_candidate(runs))
            for iid, runs in graded.items()
            if is_complete(runs)
        ]

    def measure(self, iid: str) -> None:
        """Runs 1 and 2 of one task, run 3 only if they split; then re-check the stop rule."""
        if self.stop:
            return
        solved = [self.ensure(iid, run, self.low, "cal2") for run in (1, 2)]
        if sum(solved) == 1:
            self.ensure(iid, 3, self.low, "cal2")
        with self._lock:
            self.stop = self.stop or stop_reason(self.finished_tasks())
        if self.stop:
            self.decide("stop", reason=self.stop)

    def measure_fixed(self, iid: str) -> None:
        """Exactly fixed_runs runs of one task; a confirm run has no verdict-based skipping."""
        for run in range(1, self.fixed_runs + 1):
            self.ensure(iid, run, self.low, "cal2")

    def run(self) -> None:
        """Measure candidates in order until a stop rule fires (or all fixed runs are done)."""
        try:
            measure = self.measure_fixed if self.fixed_runs else self.measure
            self.stop = None if self.fixed_runs else stop_reason(self.finished_tasks())
            self._in_parallel([lambda iid=iid: measure(iid) for iid in self.screen])
            self.state["status"] = "done"
            self.state["stop_reason"] = self.stop or "all candidates measured"
        except BlockedError as err:
            self.state["status"] = "blocked"
            self.state["blocked_reason"] = str(err)[-600:]
        finally:
            self.state["finished"] = time.time()
            self.write_summary()

    def write_summary(self) -> None:
        """Rewrite the summary atomically: header, state, totals, band counts, strata, tasks."""
        entries = [
            candidate_entry(iid, self.strata[iid], runs)
            for iid in self.screen
            if (runs := [rec for rec in self.records if rec["instance_id"] == iid])
        ]
        out = {
            **self.header,
            **self.state,
            **run_totals(self.records),
            "band_counts": {band: sum(e["band"] == band for e in entries) for band in BANDS},
            "not_started": len(self.screen) - len(entries),
            "per_stratum": per_stratum(entries),
            "tasks": entries,
        }
        tmp = self.summary_path.with_suffix(".tmp")
        with self._lock:  # one writer at a time: the tmp file name is shared
            tmp.write_text(json.dumps(out, indent=1))
            tmp.replace(self.summary_path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CAL2 candidate re-measurement driver")
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--runs-dir", required=True, help="under workdir; holds this run's log")
    parser.add_argument("--candidates-log", action="append", required=True, dest="logs")
    parser.add_argument(
        "--fixed-runs", type=int, default=0, help="N runs per listed task, in file order, no stop"
    )
    parser.add_argument("--lessons", type=Path, default=None, help="lesson arm: id -> text JSON")
    parser.add_argument("--adapter", type=int, default=None, help="personal arm: served LoRA id")
    add_limit_arguments(parser)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    driver = CandidateDriver(args.workdir, args.runs_dir, args.logs, args.fixed_runs)
    driver.low = settings_for(REASONING, args)
    driver.workers = args.workers
    if args.lessons:
        driver.give_lessons(args.lessons)
    if args.adapter is not None:
        driver.use_adapter(args.adapter)
    driver.run()
