"""Core D2 test-set selection: fixed hash order over candidates, minus tasks no model solved.

The 234 later candidates already passed the fix-area match and the commit-date rules. Here a
candidate is dropped if existing public data shows it was tried and no model ever solved it
(a task nobody solves cannot show a training effect). A candidate with no existing data stays.
Plain Glimmer's own outcomes are never read. Output is ids and counts only.
Usage: python core2_select_tests.py --split F --solves F [F ...] --out FILE [--size 100]
"""

import argparse
import hashlib
import json
from pathlib import Path

ORDER_PREFIX = "core-d2:"  # the draft's fixed hash order: sha256 of core-d2:<instance_id>


def hash_key(instance_id: str) -> str:
    """The sort key that fixes the test order before any result exists."""
    return hashlib.sha256(f"{ORDER_PREFIX}{instance_id}".encode()).hexdigest()


def merge_solves(tables: list[dict[str, list[int]]]) -> dict[str, list[int]]:
    """Per instance, [attempts, solves] summed over the data sources."""
    merged: dict[str, list[int]] = {}
    for table in tables:
        for instance, (tried, solved) in table.items():
            seen = merged.setdefault(instance, [0, 0])
            seen[0] += tried
            seen[1] += solved
    return merged


def never_solved(merged: dict[str, list[int]]) -> set[str]:
    """Instances that were tried at least once and never solved."""
    return {instance for instance, (tried, solved) in merged.items() if tried > 0 and solved == 0}


def select(candidates: list[str], merged: dict[str, list[int]], size: int) -> dict:
    """The first `size` candidates in hash order that are not never-solved, with the counts."""
    dropped = never_solved(merged) & set(candidates)
    with_data = {i for i in candidates if i in merged}
    ordered = sorted(candidates, key=hash_key)
    kept = [i for i in ordered if i not in dropped]
    return {
        "candidates": len(candidates),
        "with_existing_data": len(with_data),
        "dropped_never_solved": len(dropped),
        "kept_after_rule": len(kept),
        "test": kept[:size],
        "not_taken": len(kept[size:]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--solves", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, default=100)
    args = parser.parse_args()
    split = json.loads(args.split.read_text())
    candidates = sorted(i for repo in split.values() for i in repo["keep_ids"])
    merged = merge_solves([json.loads(path.read_text()) for path in args.solves])
    result = select(candidates, merged, args.size)
    by_repo: dict[str, int] = {}
    for instance in result["test"]:
        repo = next(name for name, entry in split.items() if instance in entry["keep_ids"])
        by_repo[repo] = by_repo.get(repo, 0) + 1
    args.out.write_text(json.dumps(result | {"test_per_repo": by_repo}, indent=1))
    print({k: v for k, v in result.items() if k != "test"} | {"per_repo": by_repo})


if __name__ == "__main__":
    main()
