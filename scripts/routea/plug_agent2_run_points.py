"""PLUG-AGENT-2 point runner: the frozen point list in its fixed order, claimed one at a time.

Several runners (one per model server) may share an output directory: a point is claimed by
creating its claim file exclusively. No point starts after the cutoff; finished points are
analyzed as they stand at the cutoff. Resumable.
Usage: plug_agent2_run_points.py POINTS OUT CONFIG SHA256 SOURCE:ROWS:LABELS:STORES:POOL:BASE ...
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

POINT_DRIVER = Path(__file__).with_name("plug_agent2_point.py")


def claim(out: Path, point_id: str) -> bool:
    """True if this runner is the first to claim the point."""
    name = hashlib.sha256(point_id.encode()).hexdigest()[:24]
    try:
        os.close(os.open(out / "claims" / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    return True


def run_point(point: dict, sources: dict[str, list[str]], args: argparse.Namespace) -> dict:
    """One point in its own child process; an empty or broken child is a void record."""
    rows, labels, stores, pool, base = sources[point["source"]]
    run = str(Path(base) / point["run"])
    command = [
        sys.executable, str(POINT_DRIVER), rows, point["task"], str(args.out / point["source"]),
        args.config, args.sha256, labels, stores, pool, run, str(point["ordinal"]), point["source"],
    ]  # fmt: skip
    child = subprocess.run(command, capture_output=True, text=True, check=False)
    lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
    record = (
        json.loads(lines[-1])
        if lines
        else {"void": {"reason": f"child failed: {child.stderr[-200:]}"}}
    )
    return record | {"point": point["id"], "source": point["source"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("points", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("config")
    parser.add_argument("sha256")
    parser.add_argument("specs", nargs="+")
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    (args.out / "claims").mkdir(parents=True, exist_ok=True)
    sources = {spec.split(":")[0]: spec.split(":")[1:] for spec in args.specs}
    cutoff, lock = datetime.strptime(args.cutoff, "%Y-%m-%d %H:%M"), threading.Lock()

    def work(point: dict) -> None:
        if datetime.now() >= cutoff or not claim(args.out, point["id"]):
            return
        record = run_point(point, sources, args)
        with lock, (args.out / "records.jsonl").open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(work, json.loads(args.points.read_text())["points"]))


if __name__ == "__main__":
    main()
