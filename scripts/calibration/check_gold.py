"""Grade the gold patch for every pool task in the shared image (prepared checkout).

A pool task whose gold patch does not resolve in the shared image cannot be graded fairly and
is dropped from calibration, listed by id with the reason. Writes <out.json>.

Usage: python check_gold.py <rows.json> <pool.json> <shared_image> <out.json> [workers]
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from taskenv import TaskEnvError, grade


def check(image: str, row: dict) -> dict:
    try:
        graded = grade(image, row, row["patch"], prepare=True)
        return {
            "instance_id": row["instance_id"],
            "gold_resolved": graded.resolved,
            "f2p": [graded.f2p_passed, graded.f2p_total],
            "p2p": [graded.p2p_passed, graded.p2p_total],
            "error": None,
        }
    except TaskEnvError as err:  # recorded per task, never dropped silently
        return {"instance_id": row["instance_id"], "gold_resolved": False, "error": str(err)[-500:]}


def main() -> None:
    rows_path, pool_path, image, out = sys.argv[1:5]
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    with open(rows_path) as rows_file, open(pool_path) as pool_file:
        rows = {row["instance_id"]: row for row in json.load(rows_file)}
        ids = [entry["instance_id"] for entry in json.load(pool_file)["pool"]]
    with ThreadPoolExecutor(workers) as executor:
        results = list(executor.map(lambda task_id: check(image, rows[task_id]), ids))
    bad = [res for res in results if not res["gold_resolved"]]
    report = {"image": image, "checked": len(results), "gold_not_resolved": bad, "results": results}
    with open(out, "w") as out_file:
        json.dump(report, out_file, indent=1)
    print(
        f"checked={len(results)} gold_not_resolved={len(bad)} "
        f"-> {[res['instance_id'] for res in bad]}"
    )


if __name__ == "__main__":
    main()
