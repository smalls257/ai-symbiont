"""Check the one-image approach before trusting it (plan Task 22, disk step).

For each given task: grade the empty patch and the gold patch twice, (a) in the task's own stock
image as shipped, (b) in the shared image after prepare_script(base_commit). The approach is
accepted only if every per-test status on FAIL_TO_PASS + PASS_TO_PASS matches between (a) and (b),
and gold resolves. Also checks that every pool base_commit exists in the shared image's clone.

Usage: python verify_disk.py <rows.json> <pool.json> <shared_image> <instance_id>...
Prints one JSON line per check; exit code 1 on any mismatch.
"""

import json
import subprocess
import sys
from dataclasses import asdict

from taskenv import Grade, grade

STOCK = "swerebench/sweb.eval.x86_64.{}"


def stock_image(iid: str) -> str:
    return STOCK.format(iid.replace("__", "_1776_"))


def missing_commits(image: str, commits: list[str]) -> list[str]:
    script = (
        "cd /testbed; for c in "
        + " ".join(commits)
        + "; do git cat-file -e $c^{commit} 2>/dev/null || echo $c; done"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image, "bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    )
    return proc.stdout.split()


def status_diff(stock: Grade, shared: Grade) -> dict[str, tuple[str, str | None]]:
    """Per-test statuses that differ between the stock image and the shared image."""
    return {
        test: (stock.status[test], shared.status.get(test))
        for test in stock.status
        if stock.status[test] != shared.status.get(test)
    }


def compare_record(iid: str, label: str, stock: Grade, shared: Grade) -> dict:
    """One output line: the grades without per-test status, plus the differences."""
    return {
        "check": "stock_vs_shared",
        "id": iid,
        "patch": label,
        "same": stock.status == shared.status and stock.resolved == shared.resolved,
        "stock": {key: val for key, val in asdict(stock).items() if key != "status"},
        "shared": {key: val for key, val in asdict(shared).items() if key != "status"},
        "diff": status_diff(stock, shared),
    }


def patch_agrees(record: dict, label: str, shared: Grade) -> bool:
    """Same result in both images, and the gold patch resolves in the shared one."""
    return record["same"] and (label != "gold" or shared.resolved)


def read_json(path: str):
    with open(path) as handle:
        return json.load(handle)


def main() -> int:
    rows_path, pool_path, shared, *ids = sys.argv[1:]
    rows = {row["instance_id"]: row for row in read_json(rows_path)}
    pool = [entry["instance_id"] for entry in read_json(pool_path)["pool"]]
    missing = missing_commits(shared, sorted({rows[iid]["base_commit"] for iid in pool}))
    print(
        json.dumps(
            {"check": "base_commits_in_shared_image", "pool": len(pool), "missing": missing}
        ),
        flush=True,
    )
    ok = not missing
    for iid in ids:
        row = rows[iid]
        for label, patch in (("empty", ""), ("gold", row["patch"])):
            stock = grade(stock_image(iid), row, patch, prepare=False)
            on_shared = grade(shared, row, patch, prepare=True)
            record = compare_record(iid, label, stock, on_shared)
            ok &= patch_agrees(record, label, on_shared)
            print(json.dumps(record), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
