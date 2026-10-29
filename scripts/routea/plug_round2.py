"""Plug round 2's split: 40 scored repos by a stable hash, validation repos, meta-training repos.

Usage: uv run python scripts/routea/plug_round2.py plan --pool P --round1 R1 --validation V --work W

Fresh repos are those with 3 to 7 distinct lessons that no earlier Plug test used. The 40 whose
name has the lowest sha256 (UTF-8 `owner/name`, hex compared as text) are scored; the rest join
meta-training. The plan is written before any scored answer; the prereg names its repos.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug import FEASIBILITY_REPOS, distinct  # noqa: E402

SCORED_COUNT = 40
FRESH_SIZES = range(3, 8)  # 3 to 7 distinct lessons


def name_hash(repo: str) -> str:
    """The sha256 of the repo's `owner/name`, as hex text."""
    return hashlib.sha256(repo.encode("utf-8")).hexdigest()


def split_round2(by_repo: dict[str, list[Lesson]], used: set[str]) -> dict:
    """Scored repos (the 40 lowest name hashes among fresh repos), meta-joining fresh repos, and
    every other unused repo for meta-training."""
    fresh = sorted(
        (r for r, items in by_repo.items() if r not in used and len(items) in FRESH_SIZES),
        key=name_hash,
    )
    if len(fresh) < SCORED_COUNT:
        raise ValueError(f"only {len(fresh)} fresh repos, need {SCORED_COUNT}")
    scored, joining = fresh[:SCORED_COUNT], fresh[SCORED_COUNT:]
    return {
        "scored": {repo: len(by_repo[repo]) for repo in sorted(scored)},
        "meta_join": {repo: len(by_repo[repo]) for repo in sorted(joining)},
    }


def main() -> None:
    """Write plan.json for round 2 from the pool and the earlier plans."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("plan",))
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--round1", type=Path, required=True, help="round 1's plan.json")
    parser.add_argument("--validation", type=Path, required=True, help="the a3 rerun's plan.json")
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    candidates, _, _ = build_lessons._candidates(args.pool, [])
    validation = set(json.loads(args.validation.read_text())["test_repos"])
    used = set(json.loads(args.round1.read_text())["test_repos"]) | validation | FEASIBILITY_REPOS
    plan = {**split_round2(distinct(candidates), used), "validation": sorted(validation)}
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "plan.json").write_text(json.dumps(plan, indent=1, sort_keys=True))
    print(json.dumps(plan, indent=1))


if __name__ == "__main__":
    main()
