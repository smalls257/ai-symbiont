"""Core D2 screening: one plain-Glimmer run per later candidate (temperature 0, 75 steps).

Each task runs in its own process; records append to <out>/runs.jsonl and a rerun skips graded
tasks. A model_api or infra error is void and retried. Screening runs never count as test runs.
Every task's image is removed right after its run, pass or fail (the 5080's disk once filled).
Usage: SYMBIONT_GLIMMER_URL=... python screen_plain.py --rows R --out DIR [--workers N]
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SETTINGS = {
    "agent": "glimmer",
    "run_label": "core2-screen",
    "step_limit": 75,
    "wall_limit_min": 45,
    "temperature": 0,
    "max_tokens_per_reply": 4096,
}


def run_one(row: dict, out: Path) -> dict:
    """One plain run in this process: the Plug harness's loop with no note."""
    from plug_agent_env import run_task  # noqa: PLC0415  heavy imports only in the child
    from plug_agent_notes import NoteArm, NoteSource  # noqa: PLC0415

    source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
    return run_task(row, source, SETTINGS, out / "traj" / f"{row['instance_id']}.traj.json")


def child_record(row: dict, rows_path: Path, out: Path) -> dict:
    """Run one task in a fresh process; a child with no record is an infra record (void)."""
    command = [sys.executable, __file__, "--rows", str(rows_path), "--out", str(out),
               "--one", row["instance_id"]]  # fmt: skip
    child = subprocess.run(command, capture_output=True, text=True, check=False)
    removed = subprocess.run(
        ["docker", "rmi", row["docker_image"]], capture_output=True, check=False
    )
    if removed.returncode:
        print(f"image not removed: {row['docker_image']}", file=sys.stderr)
    lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
    if lines:
        return json.loads(lines[-1]) | {"repo": row["repo"]}
    failed = {"error_kind": "infra", "error": child.stderr[-200:]}
    return {"instance_id": row["instance_id"], "repo": row["repo"], "resolved": None} | failed


def graded(out: Path) -> set[str]:
    """Tasks with a graded screening record."""
    log = out / "runs.jsonl"
    if not log.is_file():
        return set()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return {row["instance_id"] for row in rows if row.get("resolved") is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--one", default=None, help="internal: run one task in this process")
    args = parser.parse_args()
    rows = json.loads(args.rows.read_text())
    if args.one:
        row = next(r for r in rows if r["instance_id"] == args.one)
        print(json.dumps(run_one(row, args.out)))
        return
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [row for row in rows if row["instance_id"] not in graded(args.out)]
    with ThreadPoolExecutor(args.workers) as pool, (args.out / "runs.jsonl").open("a") as log:
        for rec in pool.map(lambda row: child_record(row, args.rows, args.out), todo):
            log.write(json.dumps(rec) + "\n")
            log.flush()


if __name__ == "__main__":
    main()
