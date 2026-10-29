"""Core D2 split check: which fix-area-matched later tasks are also later by COMMIT date.

created_at can differ from git history, so a later base commit must be strictly after every
earlier one, and under half its added lines may repeat earlier patches (revert, re-apply).
Rows stay local; the output holds ids, dates and counts only.
Usage: python core2_split_check.py --pools DIR --clones DIR --out FILE [--drop-ids FILE]
"""

import argparse
import json
import subprocess
from pathlib import Path

# Opus fix-first item 5: a later task keeps only if under half its added lines repeat earlier ones.
DUP_SHARE = 0.5


def commit_date(clone: Path, sha: str) -> str:
    """Committer date (ISO, UTC) of sha; raises if the clone lacks the commit."""
    shown = subprocess.run(
        ["git", "-C", str(clone), "show", "-s", "--format=%cI", sha],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if shown.returncode:
        raise RuntimeError(f"{clone}: no commit {sha}: {shown.stderr.strip()}")
    return shown.stdout.strip()


def patch_lines(patch: str) -> tuple[set[str], set[str]]:
    """(added lines, removed lines) of a patch, stripped, blanks and headers left out."""
    added, removed = set(), set()
    for line in patch.splitlines():
        text = line[1:].strip()
        if line.startswith("+") and not line.startswith("+++") and text:
            added.add(text)
        if line.startswith("-") and not line.startswith("---") and text:
            removed.add(text)
    return added, removed


def duplicate_share(patch: str, earlier_patches: list[str]) -> float:
    """Share of the patch's added lines that an earlier patch added or removed."""
    added, _ = patch_lines(patch)
    if not added:
        return 0.0
    seen: set[str] = set()
    for earlier in earlier_patches:
        seen |= set().union(*patch_lines(earlier))
    return len(added & seen) / len(added)


def check_repo(earlier: list[dict], later: list[dict], clone: Path) -> dict:
    """Counts and kept ids for one repository."""
    from datetime import datetime  # noqa: PLC0415

    def when(row: dict) -> datetime:
        return datetime.fromisoformat(commit_date(clone, row["base_commit"]))

    last_earlier = max(when(row) for row in earlier)
    patches = [row["patch"] for row in earlier]
    late = [row for row in later if when(row) > last_earlier]
    kept = [row for row in late if duplicate_share(row["patch"], patches) < DUP_SHARE]
    return {
        "earlier": len(earlier), "later": len(later),
        "last_earlier_base_commit_date": last_earlier.isoformat(),
        "drop_base_not_after": len(later) - len(late),
        "drop_dup_or_revert": len(late) - len(kept),
        "keep": len(kept), "keep_ids": sorted(row["instance_id"] for row in kept),
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pools", type=Path, required=True)
    parser.add_argument("--clones", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--drop-ids", type=Path, default=None, help="JSON ids never candidates")
    args = parser.parse_args()
    drop = set(json.loads(args.drop_ids.read_text())) if args.drop_ids else set()
    result = {}
    for earlier_file in sorted(args.pools.glob("*-earlier.json")):
        name = earlier_file.name.removesuffix("-earlier.json")
        earlier = json.loads(earlier_file.read_text())
        later = json.loads((args.pools / f"{name}-later.json").read_text())
        later = [row for row in later if row["instance_id"] not in drop]
        clone = args.clones / name.replace("__", "_")
        result[name] = check_repo(earlier, later, clone)
    args.out.write_text(json.dumps(result, indent=1))
    print({k: {a: v[a] for a in ("earlier", "later", "keep")} for k, v in result.items()})


if __name__ == "__main__":
    main()
