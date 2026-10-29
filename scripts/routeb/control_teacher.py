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
from pathlib import Path

from symbiont.egress.spend import Ledger

LABEL = "control-teacher"
CORE_REPOS = ("tobymao/sqlglot", "django/django")
SETTINGS = {
    "run_label": LABEL,
    "step_limit": 75,
    "wall_limit_min": 45,
    "temperature": None,  # Core's teacher runs used the server default
    "max_tokens_per_reply": 8192,  # Core's teacher runs (teacher_model.MAX_TOKENS)
}
RUN_CAP_USD = "0.15"
CHARS_PER_TOKEN = 3.5  # a stand-in until Route B counts with Glimmer's tokenizer


def phase_spent() -> float:
    """Dollars the control runs have spent so far."""
    return sum(row["cost_usd"] for row in Ledger().entries() if row["run"].startswith(LABEL))


def refuse_held(rows: list[dict], test_set: Path) -> None:
    """Raise if any row is a test task or from a Core repository."""
    held = {entry["task"] for entry in json.loads(test_set.read_text())["test"]}
    bad = [r["instance_id"] for r in rows if r["instance_id"] in held or r["repo"] in CORE_REPOS]
    if bad:
        raise ValueError(f"control rows include held-out or Core tasks: {bad[:5]}")


def passing_tokens(records: list[dict], out: Path) -> int:
    """Approximate tokens of the passing trajectories (characters / CHARS_PER_TOKEN)."""
    found = 0
    for rec in records:
        if rec.get("resolved"):
            traj = out / "traj" / f"{rec['instance_id']}.traj.json"
            found += int(len(traj.read_text()) / CHARS_PER_TOKEN)
    return found


def run_one(row: dict, out: Path) -> dict:
    """One teacher run (in this process): the Plug harness's loop with no note."""
    from plug_agent_env import run_task  # noqa: PLC0415  heavy imports only in the child
    from plug_agent_notes import NoteArm, NoteSource  # noqa: PLC0415

    source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
    return run_task(row, source, SETTINGS, out / "traj" / f"{row['instance_id']}.traj.json")


def child_record(row: dict) -> dict:
    """Run one task in a fresh process; an empty or broken child is an infra record (void)."""
    env = {**os.environ, "SYMBIONT_TEACHER_RUN_CAP_USD": RUN_CAP_USD}
    command = [sys.executable, __file__, *sys.argv[1:], "--one", row["instance_id"]]
    child = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
    removed = subprocess.run(
        ["docker", "rmi", row["docker_image"]], capture_output=True, check=False
    )
    if removed.returncode:  # the image is reclaimed after each run: the 5080's disk is shared
        print(f"image not removed: {row['docker_image']}", file=sys.stderr)
    lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
    if lines:
        return json.loads(lines[-1])
    failed = {"error_kind": "infra", "error": child.stderr[-200:]}
    return {"instance_id": row["instance_id"], "resolved": None} | failed


def stop_reason(records: list[dict], args: argparse.Namespace) -> str | None:
    """Why no further task starts, or None."""
    if phase_spent() >= args.cap_usd - float(RUN_CAP_USD):
        return "phase cap reached"
    if passing_tokens(records, args.out) >= args.target_tokens:
        return "token target reached"
    return None


def main() -> None:
    args = parse_args()
    rows = json.loads(args.rows.read_text())
    if args.one:
        row = next(r for r in rows if r["instance_id"] == args.one)
        print(json.dumps(run_one(row, args.out) | {"repo": row["repo"]}))
        return
    refuse_held(rows, args.test_set)
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.out / "runs.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []
    done = {rec["instance_id"] for rec in records}
    for row in (r for r in rows if r["instance_id"] not in done):
        reason = stop_reason(records, args)
        if reason:
            print(reason)
            break
        records.append(child_record(row))
        with log.open("a") as out:
            out.write(json.dumps(records[-1]) + "\n")
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
    return parser.parse_args()


if __name__ == "__main__":
    main()
