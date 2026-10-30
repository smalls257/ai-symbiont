"""Core D2 adapter C manifest: Spark teacher passes on OTHER repositories, earliest first by date.

Takes the control teacher's passes, refuses the six D2 repositories, every test task and every
later candidate, sorts by created_at and keeps the first COUNT, so C matches A's session count.
Trained tokens are then checked on the training host with the same builder A used.
Usage: python core2_control_manifest.py --rows R --teacher-dir DIR --split S --test-set T
         --out DIR --count 68
"""

import argparse
import json
from pathlib import Path

from core2_train_manifest import new_repo_passes, refuse, repo_of, write
from core_collect_manifest import later_candidate_ids

D2_REPOS = (
    "tobymao__sqlglot",
    "django__django",
    "streamlink__streamlink",
    "conan-io__conan",
    "iterative__dvc",
    "PennyLaneAI__pennylane",
)


def earliest(passes: list[dict], dates: dict[str, str], count: int) -> list[dict]:
    """The first `count` passes by created_at (ties by id); fewer if fewer exist."""
    return sorted(passes, key=lambda run: (dates[run["task"]], run["task"]))[:count]


def other_repos_only(passes: list[dict]) -> tuple[list[dict], int]:
    """(passes outside the six D2 repositories, how many were inside)."""
    kept = [run for run in passes if repo_of(run["task"]) not in D2_REPOS]
    return kept, len(passes) - len(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--rows", "--teacher-dir", "--split", "--test-set", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    dates = {r["instance_id"]: str(r["created_at"]) for r in json.loads(args.rows.read_text())}
    held = {
        e if isinstance(e, str) else e["task"]
        for e in json.loads(args.test_set.read_text())["test"]
    }
    held |= later_candidate_ids(json.loads(args.split.read_text()))
    passes, in_d2 = other_repos_only(new_repo_passes(args.teacher_dir))
    allowed, refused = refuse(passes, held)
    kept = earliest(allowed, dates, args.count)
    counts = {"inside_d2_repos": in_d2, "test_or_later_candidate": refused,
              "passes_available": len(allowed)}  # fmt: skip
    print(json.dumps(write(args.out, kept, counts, args.count), indent=1))


if __name__ == "__main__":
    main()
