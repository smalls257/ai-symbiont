"""PLUG-AGENT-1 runner: every kept task, five runs per task (none twice), in the prereg's order.

Refuses a config whose sha256 differs from the one the frozen prereg records, and a DRAFT prereg
unless --dry-run lists the plan without a call. The spend cap is checked only between tasks,
so every finished task has all five runs. Resumable: a (task, arm) with a graded record is done.
Usage: python plug_agent_run.py --prereg P --config C --rows R --tasks T --pool D --plan J
         --dates J --selection J --judge-url U --out DIR [--dry-run]
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import build_lessons
from lessons import lessons_in_session
from plug import distinct
from plug_agent_env import run_task
from plug_agent_notes import JudgeDownError, NoteArm, NoteSource, Scorer, judge_client
from plug_agent_store import Store, store_for

from symbiont.egress.spend import Ledger

RUN_CAP_VARIABLE = "SYMBIONT_TEACHER_RUN_CAP_USD"
SHA_LINE = re.compile(r"config sha256: `?([0-9a-f]{64})`?")


class Mode(StrEnum):
    """Run the arms, or only list what would run."""

    LIVE = "live"
    DRY = "dry"


def order_key(*parts: str) -> str:
    """sha256 of `plug-agent-1:<parts>`: the prereg's task and arm order."""
    return hashlib.sha256(":".join(("plug-agent-1", *parts)).encode()).hexdigest()


def checked_config(prereg: Path, config: Path, mode: Mode) -> dict:
    """The config, after its sha256 matches the prereg's; raises SystemExit otherwise."""
    if "DRAFT" in prereg.name and mode is Mode.LIVE:
        raise SystemExit(f"{prereg.name} is a draft: freeze it first (or use --dry-run)")
    found = SHA_LINE.search(prereg.read_text())
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    if mode is Mode.LIVE and (found is None or found.group(1) != digest):
        raise SystemExit(f"config sha256 {digest} is not the prereg's; refusing to run")
    loaded = json.loads(config.read_text())
    blank = sorted(key for key, value in loaded.items() if value in (None, ""))
    if blank:
        raise SystemExit(f"config fields blank: {blank}")
    return loaded


def lesson_pool(pool: Path) -> tuple[dict, dict[str, str]]:
    """Lessons by repo (`plug.distinct`) and each lesson's source instance."""
    instance_of: dict[str, str] = {}
    candidates = []
    for session in build_lessons._sessions(pool, []):
        found = lessons_in_session(session, Counter())
        candidates += found
        instance_of |= {lesson.lesson_id: session[0].task_id for lesson in found}
    return distinct(candidates), instance_of


def phase_spent() -> float:
    """Dollars this phase's runs have spent (their ledger run names start with the phase id)."""
    return sum(
        row["cost_usd"] for row in Ledger().entries() if row["run"].startswith("plug-agent-1-")
    )


def done(out: Path) -> set[tuple[str, str]]:
    """(task, arm) pairs that already have a graded record."""
    log = out / "runs.jsonl"
    if not log.is_file():
        return set()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return {(r["instance_id"], r["arm"]) for r in rows if r.get("resolved") is not None}


@dataclass(frozen=True)
class Plan:
    """Everything every run of the phase shares."""

    config: dict
    by_repo: dict
    instance_of: dict[str, str]
    dates: dict[str, str | None]
    scored: frozenset[str]
    thresholds: dict
    judge: Scorer | None
    out: Path
    mode: Mode

    def store(self, task: str, row: dict) -> Store:
        """The task's store (only earlier instances' lessons)."""
        created = {"instance_id": task, "repo": row["repo"], "created_at": str(row["created_at"])}
        return store_for(created, self.by_repo, self.instance_of, self.dates, self.scored)

    def source(self, arm: NoteArm, row: dict, store: Store) -> NoteSource:
        """The arm's note source for one run."""
        judge = self.judge if arm is NoteArm.JUDGE else None
        ranker, judged = self.thresholds["ranker_threshold"], self.thresholds["judge"]
        return NoteSource(arm, row["repo"], store.candidates, ranker, judged, judge)


def run_until_graded(run_once: Callable[[], dict], requeues: int) -> tuple[dict | None, list[dict]]:
    """(the graded record or None, the void records). A void run is retried `requeues` times.

    Void = resolved None (infra, model_api, grader error): never scored, never silently dropped.
    """
    voids: list[dict] = []
    for _ in range(requeues + 1):
        rec = run_once()
        if rec.get("resolved") is not None:
            return rec, voids
        voids.append(rec)
    return None, voids


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a") as log:
        log.write(json.dumps(row) + "\n")


def dropped_tasks(out: Path) -> set[str]:
    """Tasks that stayed void after their requeue: excluded from all five runs in the analysis."""
    log = out / "dropped.jsonl"
    if not log.is_file():
        return set()
    return {json.loads(line)["instance_id"] for line in log.read_text().splitlines() if line}


def scored_records(out: Path) -> list[dict]:
    """The graded records of tasks that were not dropped."""
    log = out / "runs.jsonl"
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    gone = dropped_tasks(out)
    return [r for r in rows if r.get("resolved") is not None and r["instance_id"] not in gone]


def run_arm(plan: Plan, task: str, row: dict, arm: NoteArm, store: Store) -> bool:
    """One arm: graded record written (True), or void after its requeues, task dropped (False)."""
    traj = plan.out / "traj" / task / f"{arm}.traj.json"
    extra = {"store": len(store.candidates), "removed": store.removed_counts()}
    rec, voids = run_until_graded(
        lambda: run_task(row, plan.source(arm, row, store), plan.config, traj),
        plan.config["void_requeue_cap"],
    )
    for void in voids:
        append_jsonl(plan.out / "voids.jsonl", void | extra)
    if rec is not None:
        append_jsonl(plan.out / "runs.jsonl", rec | extra)
        return True
    last = voids[-1]
    reason = last.get("error_kind") or last.get("grade_error") or "ungraded"
    append_jsonl(
        plan.out / "dropped.jsonl", {"instance_id": task, "arm": str(arm), "reason": reason}
    )
    return False


def run_arms(plan: Plan, task: str, row: dict, finished: set[tuple[str, str]]) -> None:
    """All five runs of one task (none twice), in the prereg's arm order.

    An arm that stays void after its requeue drops the task from all five runs (dropped.jsonl) and
    no later arm runs. A down judge raises JudgeDownError out of here and stops the whole phase.
    """
    store = plan.store(task, row)
    for arm in sorted(NoteArm, key=lambda arm: order_key(task, arm)):
        if (task, str(arm)) in finished:
            continue
        if plan.mode is Mode.DRY:
            print(task, arm, len(store.candidates), store.removed_counts())
        elif not run_arm(plan, task, row, arm, store):
            return


def main() -> None:
    args = parse_args()
    mode = Mode.DRY if args.dry_run else Mode.LIVE
    config = checked_config(args.prereg, args.config, mode)
    spark = config["agent"] == "spark"
    if spark:  # a paid agent: per-run cap; the ledger's total cap stays the owner's
        os.environ[RUN_CAP_VARIABLE] = str(config["per_run_cap_usd"])
    by_repo, instance_of = lesson_pool(args.pool)
    plan = Plan(
        config=config,
        by_repo=by_repo,
        instance_of=instance_of,
        dates=json.loads(args.dates.read_text()),
        scored=frozenset(json.loads(args.plan.read_text())["scored"]),
        thresholds=json.loads(args.selection.read_text())["thresholds"],
        judge=None if mode is Mode.DRY else judge_client(args.judge_url),
        out=args.out,
        mode=mode,
    )
    rows = {row["instance_id"]: row for row in json.loads(args.rows.read_text())}
    args.out.mkdir(parents=True, exist_ok=True)
    finished = done(args.out)
    dropped = dropped_tasks(args.out)
    for task in sorted(json.loads(args.tasks.read_text())["kept"], key=order_key):
        if task in dropped:
            continue
        if spark and phase_spent() >= config["phase_cap_usd"] - config["per_run_cap_usd"] * len(
            NoteArm
        ):
            print(f"spend cap reached before {task}; stopping")
            break
        try:
            run_arms(plan, task, rows[task], finished)
        except JudgeDownError as error:
            raise SystemExit(
                f"STOPPED at {task}: {error}; no arm runs without its judge"
            ) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    paths = ("--prereg", "--config", "--rows", "--tasks", "--pool", "--plan", "--dates")
    for flag in (*paths, "--selection", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--judge-url", default="http://127.0.0.1:8791/score")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
