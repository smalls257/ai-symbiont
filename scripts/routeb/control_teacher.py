"""Control-adapter data: Spark teacher runs on earlier tasks of OTHER repositories.

Same agent loop and caps as Core's teacher runs ($0.15 a run, 75 steps, no note). Each task
runs in its own process, so a long run's memory dies with it; the parent stops at the phase cap
or once the passing runs reach the token target. Refuses any test-set task or Core repository.
Usage: python control_teacher.py --rows R --test-set T --out DIR --cap-usd 3 --target-tokens N
"""

import argparse
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from symbiont.egress.spend import Ledger

LABEL = "control-teacher"  # --label overrides it (core2-teacher for the D2 target set)
CORE_REPOS = (  # Core D2 repositories: never in the control set
    "tobymao/sqlglot",
    "django/django",
    "streamlink/streamlink",
    "conan-io/conan",
    "iterative/dvc",
    "PennyLaneAI/pennylane",
)
SETTINGS = {
    "agent": "spark",
    "run_label": LABEL,
    "step_limit": 75,
    "wall_limit_min": 45,
    "temperature": None,  # Core's teacher runs used the server default
    "max_tokens_per_reply": 8192,  # Core's teacher runs (teacher_model.MAX_TOKENS)
}
RUN_CAP_USD = "0.15"
CHARS_PER_TOKEN = 3.5  # a stand-in until Route B counts with Glimmer's tokenizer
CUT_TOKENS = 16_384  # Route B cuts each run at the last whole turn within 16k
MIN_PASSES = 96  # Route B: 80 rows plus 20% overshoot


def phase_spent() -> float:
    """Dollars this phase's runs (ledger names starting with its label) have spent so far."""
    return sum(
        row["cost_usd"]
        for row in Ledger().entries()
        if row["run"].startswith(SETTINGS["run_label"])
    )


def later_candidate_ids(path: Path) -> set[str]:
    """Every later candidate named in split-check.json (the tasks no training run may touch)."""
    return {task for repo in json.loads(path.read_text()).values() for task in repo["keep_ids"]}


def refuse_held(rows: list[dict], test_set: Path, later: set[str] | None = None) -> None:
    """Raise if any row is a test task, a later candidate, or (control runs) a Core repository.

    Control runs (later is None) must come from other repositories. Core's own teacher runs
    (later given) are on Core repositories by design, so the guard is the later-candidate list.
    """
    held = {
        e if isinstance(e, str) else e["task"] for e in json.loads(test_set.read_text())["test"]
    }
    if later is None:
        bad = [
            r["instance_id"] for r in rows if r["instance_id"] in held or r["repo"] in CORE_REPOS
        ]
        if bad:
            raise ValueError(f"control rows include held-out or Core tasks: {bad[:5]}")
        return
    bad = [r["instance_id"] for r in rows if r["instance_id"] in held | later]
    if bad:
        raise ValueError(f"teacher rows include held-out or later-candidate tasks: {bad[:5]}")


def passing_tokens(records: list[dict], out: Path) -> int:
    """Approximate tokens of the passing trajectories after the 16k cut (characters / 3.5)."""
    found = 0
    for rec in records:
        if rec.get("resolved"):
            traj = out / "traj" / f"{rec['instance_id']}.traj.json"
            found += min(int(len(traj.read_text()) / CHARS_PER_TOKEN), CUT_TOKENS)
    return found


def run_one(row: dict, out: Path) -> dict:
    """One teacher run (in this process): the Plug harness's loop with no note."""
    from plug_agent_env import run_task  # noqa: PLC0415  heavy imports only in the child
    from plug_agent_notes import NoteArm, NoteSource  # noqa: PLC0415

    source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
    return run_task(row, source, SETTINGS, out / "traj" / f"{row['instance_id']}.traj.json")


def voided_if_ledger_mismatch(rec: dict) -> dict:
    """A run that died on a spend-ledger mismatch never reached the model: void, not a fail."""
    if rec.get("exit_status") != "LedgerMismatchError":
        return rec
    return rec | {"resolved": None, "error_kind": "infra"}


def child_record(row: dict) -> dict:
    """Run one task in a fresh process; an empty or broken child is an infra record (void)."""
    Ledger().rebuild_total()  # other hosts' processes may append without the running total
    env = {**os.environ, "SYMBIONT_TEACHER_RUN_CAP_USD": RUN_CAP_USD}
    command = [sys.executable, __file__, *sys.argv[1:], "--one", row["instance_id"]]
    child = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
    removed = subprocess.run(
        ["docker", "rmi", "-f", row["docker_image"]], capture_output=True, check=False
    )
    if removed.returncode:  # the image is reclaimed after each run: the 5080's disk is shared
        print(f"image not removed: {row['docker_image']}", file=sys.stderr)
    lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
    if lines:
        return voided_if_ledger_mismatch(json.loads(lines[-1]))
    failed = {"error_kind": "infra", "error": child.stderr[-200:]}
    return {"instance_id": row["instance_id"], "resolved": None} | failed


def balanced_by_date(rows: list[dict]) -> list[dict]:
    """Rows interleaved across repositories, each repository's earliest task (created_at) first.

    With a per-repository pass cap this keeps the repositories balanced whatever the results
    are: the order is fixed by dates alone, before any run.
    """
    by_repo: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda row: (str(row["created_at"]), row["instance_id"])):
        by_repo.setdefault(row["repo"], []).append(row)
    queues = [by_repo[repo] for repo in sorted(by_repo)]
    return [q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)]


def repo_is_full(records: list[dict], repo: str, per_repo_passes: int | None) -> bool:
    """The repository already has its share of passing sessions (no cap when None)."""
    if per_repo_passes is None:
        return False
    return sum(bool(r.get("resolved")) for r in records if r.get("repo") == repo) >= per_repo_passes


def stop_reason(records: list[dict], args: argparse.Namespace) -> str | None:
    """Why no further task starts, or None."""
    if phase_spent() >= args.cap_usd - float(RUN_CAP_USD):
        return "phase cap reached"
    passes = sum(bool(rec.get("resolved")) for rec in records)
    if args.max_passes is not None and passes >= args.max_passes:
        return "pass target reached"
    if passes >= MIN_PASSES and passing_tokens(records, args.out) >= args.target_tokens:
        return "token target reached"
    return None


def main() -> None:
    args = parse_args()
    SETTINGS["run_label"] = args.label
    rows = json.loads(args.rows.read_text())
    if args.one:
        row = next(r for r in rows if r["instance_id"] == args.one)
        print(json.dumps(run_one(row, args.out) | {"repo": row["repo"]}))
        return
    later = later_candidate_ids(args.later_candidates) if args.later_candidates else None
    refuse_held(rows, args.test_set, later)
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.out / "runs.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []
    done = {rec["instance_id"] for rec in records if rec.get("resolved") is not None}  # voids rerun
    lock = threading.Lock()

    def worker(row: dict) -> None:
        with lock:
            reason = stop_reason(records, args)
            full = repo_is_full(records, row["repo"], args.per_repo_passes)
        if reason or full:
            return
        rec = child_record(row)
        with lock, log.open("a") as out:
            records.append(rec)
            out.write(json.dumps(rec) + "\n")

    todo = balanced_by_date([r for r in rows if r["instance_id"] not in done])
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(worker, todo))  # the stop rule is checked before each task starts
    passes = sum(bool(r.get("resolved")) for r in records)
    tokens = passing_tokens(records, args.out)
    print(json.dumps({"runs": len(records), "passes": passes, "tokens": tokens,
                      "spent": round(phase_spent(), 3)}))  # fmt: skip


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--test-set", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cap-usd", type=float, default=3.0)
    parser.add_argument("--target-tokens", type=int, default=1_200_000)
    parser.add_argument("--one", default=None, help="internal: run one task in this process")
    parser.add_argument(
        "--later-candidates", type=Path, default=None,
        help="split-check.json: a Core earlier-task run that refuses these later tasks",
    )  # fmt: skip
    parser.add_argument(
        "--per-repo-passes",
        type=int,
        default=None,
        help="no new task of a repository after N passes",
    )
    parser.add_argument("--max-passes", type=int, default=None, help="stop at this many passes")
    parser.add_argument("--label", default=LABEL, help="ledger run-name prefix of this phase")
    parser.add_argument("--workers", type=int, default=1, help="tasks run at once")
    return parser.parse_args()


if __name__ == "__main__":
    main()
