"""CAL2: three plain-Glimmer runs per already-screened task under a higher step cap.

Violation prevented: **Paper Tiger**. The first calibration screened tasks at a 50-step cap and
nearly every unsolved run simply ran out of steps, so its "history" band mixed hard tasks with
tasks the cap cut off. CAL2 re-measures every screened task, three runs each, at a raised cap and
keeps those plain Glimmer solves 1 or 2 times of 3 (about 20-60%). Unlike staged.py there is no
screen gate: a task that fails run 1 may still land in band, so every candidate gets all 3 runs.

Runs go run-major (run 1 of every task, then run 2, then run 3) so a partial log is already a
fair, same-depth sample of every task. The log is resumable (staged.Driver.graded). The summary
holds ids, counts and labels only.

Usage (through launch.py): python launch.py <workdir> --candidates-log runs/calibration.jsonl
        --candidates-log runs-wide/calibration.jsonl --runs-dir runs-cal2 --step-limit 75
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from screen_rules import cells_of
from staged import (
    BlockedError,
    Driver,
    add_limit_arguments,
    read_logged_ids,
    settings_for,
)
from staged_summary import RUN_FIELDS, RUNS_PER_TASK, run_totals

REASONING = "low"  # every earlier screen run used "low"; no medium run exists to compare with
BANDS = ("in_band", "too_easy", "too_hard", "pending")


def band_of_candidate(graded_runs: list[dict]) -> str:
    """Where a candidate stands: in_band when 1 or 2 of its 3 runs solved, else too easy or hard.

    "pending" until all RUNS_PER_TASK runs are graded; a partial log never claims a band.
    """
    if len({rec["run"] for rec in graded_runs}) < RUNS_PER_TASK:
        return "pending"
    solved = sum(rec["resolved"] for rec in graded_runs)
    if solved == 0:
        return "too_hard"
    return "too_easy" if solved == RUNS_PER_TASK else "in_band"


def candidate_ids(workdir: Path, logs: list[str]) -> list[str]:
    """Sorted ids of every task in the given earlier logs; raises if a log is missing."""
    ids: set[str] = set()
    for log in logs:
        ids |= read_logged_ids(workdir / log)
    return sorted(ids)


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
    """Three runs of every candidate at one setting; summary by band and stratum."""

    def __init__(self, workdir: Path, runs_dir: str, logs: list[str]):
        super().__init__(workdir, runs_dir=runs_dir)
        pool = json.loads((workdir / "data/pool.json").read_text())["pool"]
        self.screen = candidate_ids(workdir, logs)
        self.strata = stratum_labels(pool, self.screen)
        self.header = self.header | {
            "plan": f"CAL2: {len(self.screen)} candidates x {RUNS_PER_TASK} runs, run-major; "
            "in band = 1-2 of 3",
            "candidate_logs": logs,
        }
        self.state["stage"] = "cal2"
        self.state["setting"] = REASONING

    def run(self) -> None:
        """Run 1, then 2, then 3 for every candidate; always write the final summary."""
        setting = self.low
        try:
            for run in range(1, RUNS_PER_TASK + 1):
                self.decide("run_round", run=run, tasks=len(self.screen))
                self._in_parallel([self._job(iid, run, setting, "cal2") for iid in self.screen])
            self.state["status"] = "done"
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
            "per_stratum": per_stratum(entries),
            "tasks": entries,
        }
        tmp = self.summary_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=1))
        tmp.replace(self.summary_path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CAL2 candidate re-measurement driver")
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--runs-dir", required=True, help="under workdir; holds this run's log")
    parser.add_argument("--candidates-log", action="append", required=True, dest="logs")
    add_limit_arguments(parser)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    driver = CandidateDriver(args.workdir, args.runs_dir, args.logs)
    driver.low = settings_for(REASONING, args)
    driver.run()
