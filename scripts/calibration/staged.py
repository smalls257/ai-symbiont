"""Staged Glimmer calibration driver (lead's ruling, 2026-10-27).

Stage 1, screen: SCREEN_N pool tasks chosen by a named ScreenRule (screen_rules.py): SMALLEST (the
smallest gold patches, the default) or STRATIFIED (spread over subsystem x size cells, skipping the
ids of an earlier log). 1 run each, reasoning "low", step limit 50 and 30 min wall cap by default
(launcher settings --step-limit and --wall-limit-min).
  Checkpoint after the first CHECKPOINT_N runs: if none solved, the same tasks are run again with
  reasoning "medium"; the setting that solves more is used for the remaining screen tasks (tie ->
  "low"). The decision is logged with its counts.
  Gate: if medium was tried and the screen still solves under 10%, stop with status "gate_fail".
Stage 2: every task solved in the screen gets 2 more runs with the same setting. Solved 1 or 2 of 3
  -> band "in_band" (scored pool); otherwise "history".

Up to --workers runs go at a time (default WORKERS, the Glimmer slot count); the checkpoint
batch finishes before the decision. All records append to
<workdir>/<runs-dir>/calibration.jsonl (resumable: a run counts as done once it has a graded
record). Runs that could not be graded are retried up to MAX_ATTEMPTS times; 3 ungraded runs in
a row stop the driver with status "blocked" (a run already in flight on another worker still
lands). After every run the summary (no task or
trajectory text) is rewritten to <workdir>/<runs-dir>/calibration-glimmer.json.

Usage: python staged.py <workdir> [--screen smallest|stratified] [--runs-dir runs]
                        [--step-limit 50] [--wall-limit-min 30]
                        [--exclude-log runs/calibration.jsonl]
(start it through launch.py; a stratified run needs its own --runs-dir)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from run_calibration import IMAGE, MODEL, Setting, run_once
from screen_rules import (
    SCREEN_N,
    STRATIFIED_SEED,
    ScreenRule,
    pick_counts,
    select_screen,
)
from staged_summary import build_summary

WORKERS = 2  # default: the Glimmer server had 2 slots; --workers follows a slot change
CHECKPOINT_N = 10
GATE_RATE = 0.10
MAX_ATTEMPTS = 3
MAX_UNGRADED_IN_A_ROW = 3
DEFAULT_STEP_LIMIT = 50
DEFAULT_WALL_LIMIT_MIN = 30
ANNOUNCED = (
    "instance_id",
    "stage",
    "run",
    "reasoning",
    "exit_status",
    "steps",
    "resolved",
    "wall_s",
    "error_kind",
)
SUMMARY_HEADER = {
    "model": MODEL,
    "harness": "mini-swe-agent 2.4.6, swebench.yaml (tool calling)",
    "image": IMAGE,
    "checkout": (
        "history-free depth-1 checkout of base_commit per run, no network "
        "(stock per-task images expose future git history incl. the fix)"
    ),
    "plan": f"screen {SCREEN_N} tasks x1 (checkpoint after {CHECKPOINT_N}), "
    "solved tasks x2 more; in band = 1-2 of 3",
}


def screen_header(rule: ScreenRule, pool: list[dict], screen: list[str], excluded: int) -> dict:
    """Summary header fields for the screen rule: rule, seed, per-cell counts (labels only)."""
    header = {"screen_rule": str(rule), "screen_excluded_ids": excluded}
    if rule is ScreenRule.STRATIFIED:
        header |= {"screen_seed": STRATIFIED_SEED, "screen_cells": pick_counts(pool, screen)}
    return header


def read_logged_ids(log: Path) -> set[str]:
    """Instance ids present in an earlier calibration.jsonl; raises if the file is missing."""
    return {json.loads(line)["instance_id"] for line in log.read_text().splitlines() if line}


def add_limit_arguments(parser: argparse.ArgumentParser) -> None:
    """The step cap and wall cap as launcher settings; defaults are the original 50 and 30 min."""
    parser.add_argument("--step-limit", type=int, default=DEFAULT_STEP_LIMIT)
    parser.add_argument("--wall-limit-min", type=int, default=DEFAULT_WALL_LIMIT_MIN)
    parser.add_argument("--workers", type=int, default=WORKERS, help="Glimmer slots to fill")


def settings_for(reasoning: str, args: argparse.Namespace) -> Setting:
    """The run setting for a reasoning strength under the launcher's step and wall caps."""
    return Setting(reasoning, args.step_limit, args.wall_limit_min * 60)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command line; the defaults reproduce the original `staged.py <workdir>` run."""
    parser = argparse.ArgumentParser(description="Staged Glimmer calibration driver")
    parser.add_argument("workdir", type=Path)
    add_limit_arguments(parser)
    parser.add_argument("--screen", type=ScreenRule, choices=list(ScreenRule), default="smallest")
    parser.add_argument("--runs-dir", default="runs", help="under workdir; holds this run's log")
    parser.add_argument(
        "--exclude-log", default=None, help="under workdir; its task ids are skipped"
    )
    return parser.parse_args(argv)


class BlockedError(RuntimeError):
    """Too many ungraded runs in a row: Glimmer or Docker is down."""


class Driver:
    """Runs the screen and confirm stages, resumable from the append-only record log."""

    def __init__(
        self,
        workdir: Path,
        rule: ScreenRule = ScreenRule.SMALLEST,
        runs_dir: str = "runs",
        exclude_log: str | None = None,
    ):
        self.low = Setting("low", DEFAULT_STEP_LIMIT, DEFAULT_WALL_LIMIT_MIN * 60)
        self.medium = Setting("medium", DEFAULT_STEP_LIMIT, DEFAULT_WALL_LIMIT_MIN * 60)
        self.rows = {
            row["instance_id"]: row
            for row in json.loads((workdir / "data/sqlglot_rows.json").read_text())
        }
        pool = json.loads((workdir / "data/pool.json").read_text())["pool"]
        excluded = read_logged_ids(workdir / exclude_log) if exclude_log else set()
        self.screen = select_screen(rule, pool, excluded)
        self.header = SUMMARY_HEADER | screen_header(rule, pool, self.screen, len(excluded))
        self.runs_dir = workdir / runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.log = self.runs_dir / "calibration.jsonl"
        self.summary_path = self.runs_dir / "calibration-glimmer.json"
        self.records = (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )
        self.state = {
            "status": "running",
            "stage": "screen",
            "setting": None,
            "decisions": [],
            "started": time.time(),
        }
        self.ungraded_in_a_row = 0
        self._lock = threading.Lock()
        self._blocked_reason: str | None = None
        self.workers = WORKERS

    # -- records -----------------------------------------------------------------------------------
    def graded(self, iid: str, run: int, setting: Setting) -> dict | None:
        """The graded record of this (task, run, setting), if one exists."""
        for rec in self.records:
            if (rec["instance_id"], rec["run"], rec["reasoning"], rec["step_limit"]) == (
                iid,
                run,
                setting.reasoning,
                setting.step_limit,
            ) and rec["resolved"] is not None:
                return rec
        return None

    def ensure(self, iid: str, run: int, setting: Setting, stage: str) -> bool:
        """Make sure (task, run, setting) has a graded record; return whether it resolved."""
        if done := self.graded(iid, run, setting):
            return done["resolved"]
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._blocked_reason:  # a sibling worker hit the block: no new run may start
                raise BlockedError(self._blocked_reason)
            rec = run_once(self.rows[iid], run, setting, stage, self.runs_dir / "traj")
            rec = rec | {"attempt": attempt}
            self._record(rec)
            if rec["resolved"] is not None:
                return rec["resolved"]
        return False  # every attempt ungraded: counted unsolved; visible as resolved=None records

    def _record(self, rec: dict) -> None:
        """Append, announce and summarize one run; raise BlockedError after too many ungraded.

        One lock covers the append, the announce, the counter and the summary write, so two
        workers never interleave log lines or race the ungraded count.
        """
        with self._lock:
            self.records.append(rec)
            with self.log.open("a") as handle:
                handle.write(json.dumps(rec) + "\n")
            print(json.dumps({key: rec.get(key) for key in ANNOUNCED}), flush=True)
            graded = rec["resolved"] is not None
            self.ungraded_in_a_row = 0 if graded else self.ungraded_in_a_row + 1
            self.write_summary()
            if self.ungraded_in_a_row >= MAX_UNGRADED_IN_A_ROW:
                self._blocked_reason = (
                    f"{self.ungraded_in_a_row} ungraded runs in a row; last error: {rec['error']}"
                )
                raise BlockedError(self._blocked_reason)

    def _in_parallel(self, jobs: list) -> list:
        """Results of zero-argument jobs, self.workers at a time, in order; first error raised."""
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(job) for job in jobs]
            return [future.result() for future in futures]

    def decide(self, what: str, **detail) -> None:
        """Log a decision with its counts, in the summary and on stdout."""
        self.state["decisions"].append(
            {"what": what, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **detail}
        )
        print("DECISION", json.dumps(self.state["decisions"][-1]), flush=True)
        self.write_summary()

    # -- stages ------------------------------------------------------------------------------------
    def stage1(self) -> Setting:
        """Screen with low reasoning; rerun the checkpoint on medium if low solved none."""
        first = self.screen[:CHECKPOINT_N]
        low = sum(self._in_parallel([self._job(iid, 1, self.low, "screen") for iid in first]))
        setting = self.low
        if low == 0:
            med = sum(
                self._in_parallel(
                    [self._job(iid, 1, self.medium, "screen-checkpoint") for iid in first]
                )
            )
            setting = self.medium if med > low else self.low
            self.decide(
                "checkpoint",
                low_solved=low,
                medium_solved=med,
                of=len(first),
                chosen=setting.reasoning,
                rule="0/10 on low -> rerun on medium; more solved wins, tie -> low",
            )
        else:
            self.decide(
                "checkpoint",
                low_solved=low,
                of=len(first),
                chosen="low",
                rule="low solved >= 1 -> keep low",
            )
        self.state["setting"] = setting.reasoning
        self._in_parallel(
            [self._job(iid, 1, setting, "screen") for iid in self.screen[CHECKPOINT_N:]]
        )
        return setting

    def _job(self, iid: str, run: int, setting: Setting, stage: str):
        """A zero-argument job that ensures one (task, run, setting)."""
        return lambda: self.ensure(iid, run, setting, stage)

    def stage2(self, setting: Setting) -> None:
        """Two more runs for every task the screen solved."""
        self.state["stage"] = "confirm"
        self._in_parallel(
            [
                self._job(iid, run, setting, "confirm")
                for iid in self.solved_in_screen(setting)
                for run in (2, 3)
            ]
        )

    def solved_in_screen(self, setting: Setting) -> list[str]:
        """Screen tasks whose run 1 resolved with this setting."""
        return [
            iid for iid in self.screen if (rec := self.graded(iid, 1, setting)) and rec["resolved"]
        ]

    def run(self) -> None:
        """Run both stages, stopping at the gate or when blocked; always write the final summary."""
        try:
            setting = self.stage1()
            if self._screen_fails_gate(setting):
                self.state["status"] = "gate_fail"
                return
            self.state["status"] = "screen_done"
            self.write_summary()
            self.stage2(setting)
            self.state["status"] = "done"
        except BlockedError as err:
            self.state["status"] = "blocked"
            self.state["blocked_reason"] = str(err)[-600:]
        finally:
            self.state["finished"] = time.time()
            self.write_summary()

    def _screen_fails_gate(self, setting: Setting) -> bool:
        """Log the screen result; true if medium was tried and the solve rate is under GATE_RATE."""
        solved = len(self.solved_in_screen(setting))
        rate = solved / len(self.screen)
        medium_tried = any(rec["reasoning"] == "medium" for rec in self.records)
        self.decide(
            "screen_done",
            solved=solved,
            of=len(self.screen),
            rate=round(rate, 3),
            medium_tried=medium_tried,
        )
        return rate < GATE_RATE and medium_tried

    def write_summary(self) -> None:
        """Rewrite the summary file atomically so a reader never sees half of it."""
        out = build_summary(self.header, self.state, self.screen, self.records)
        tmp = self.summary_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=1))
        tmp.replace(self.summary_path)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    driver = Driver(args.workdir, args.screen, args.runs_dir, args.exclude_log)
    driver.low, driver.medium = settings_for("low", args), settings_for("medium", args)
    driver.workers = args.workers
    driver.run()
