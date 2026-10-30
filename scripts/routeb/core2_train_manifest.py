"""Core D2 adapter A manifest: Spark teacher passes on earlier tasks, capped per repository.

Refuses every test task and later candidate, keeps each repository's earliest passes by date up
to the cap, and copies the trajectories beside manifest.jsonl (build_sft_set format) so one
directory moves to the training host. Ids, counts and the manifest sha256 only.
Usage: python core2_train_manifest.py --split S --test-set T --dates D --out DIR --cap 14
         --teacher-dir DIR --old-manifest M --old-dir DIR
"""

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from core_collect_manifest import later_candidate_ids

SOURCE = "teacher/spark"


def repo_of(instance_id: str) -> str:
    """'streamlink__streamlink-5444' -> 'streamlink__streamlink'."""
    return instance_id.rsplit("-", 1)[0]


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def new_repo_passes(teacher_dir: Path) -> list[dict]:
    """Passing runs of the teacher driver: {task, path} per resolved record, trajectory required."""
    found = []
    for row in jsonl(teacher_dir / "runs.jsonl"):
        if row.get("resolved") is not True:
            continue
        path = teacher_dir / "traj" / f"{row['instance_id']}.traj.json"
        if not path.is_file():
            raise FileNotFoundError(f"resolved run without a trajectory: {path}")
        found.append({"task": row["instance_id"], "path": path})
    return found


def old_passes(manifest: Path, old_dir: Path) -> list[dict]:
    """The earlier sqlglot and Django teacher passes (Route B's first manifest), Spark only."""
    found = []
    for row in jsonl(manifest):
        if row.get("source") != SOURCE or row.get("resolved") is not True:
            continue
        path = old_dir / f"{row['instance_id']}-run1-p1.traj.json"
        if not path.is_file():
            raise FileNotFoundError(f"teacher pass without a trajectory: {path}")
        found.append({"task": row["instance_id"], "path": path})
    return found


def capped(passes: list[dict], dates: dict[str, str], cap: int) -> list[dict]:
    """Each repository's earliest `cap` passes by created_at. A repository over the cap needs
    dates for all its passes (KeyError names the id); one at or under the cap needs none."""
    by_repo: dict[str, list[dict]] = {}
    for run in passes:
        by_repo.setdefault(repo_of(run["task"]), []).append(run)
    kept: list[dict] = []
    for repo in sorted(by_repo):
        runs = by_repo[repo]
        if len(runs) > cap:
            runs = sorted(runs, key=lambda run: (dates[run["task"]], run["task"]))[:cap]
        kept += sorted(runs, key=lambda run: run["task"])
    return kept


def refuse(passes: list[dict], held: set[str]) -> tuple[list[dict], int]:
    """(passes not in `held`, how many were refused)."""
    kept = [run for run in passes if run["task"] not in held]
    return kept, len(passes) - len(kept)


def outside_earlier_pool(passes: list[dict], pool: set[str]) -> tuple[list[dict], int]:
    """Drop passes of a pooled repository that are not in its earlier pool (e.g. sqlglot's 161)."""
    pooled = {repo_of(task) for task in pool}
    kept = [r for r in passes if repo_of(r["task"]) not in pooled or r["task"] in pool]
    return kept, len(passes) - len(kept)


def write(out: Path, kept: list[dict], refused: dict[str, int], cap: int) -> dict:
    """Copy the trajectories, write the manifest and its counts; returns the counts."""
    (out / "traj").mkdir(parents=True, exist_ok=True)
    lines, details = [], []
    for run in kept:
        name = f"{run['task']}.traj.json"
        shutil.copyfile(run["path"], out / "traj" / name)
        lines.append({"instance_id": run["task"], "path": f"traj/{name}", "resolved": True,
                      "source": SOURCE})  # fmt: skip
        details.append({"task": run["task"], "repo": repo_of(run["task"]), "path": f"traj/{name}"})
    text = "".join(json.dumps(line) + "\n" for line in lines)
    (out / "manifest.jsonl").write_text(text)
    (out / "details.jsonl").write_text("".join(json.dumps(d) + "\n" for d in details))
    counts = {
        "passes": len(kept),
        "per_repo": dict(Counter(d["repo"] for d in details)),
        "refused": refused,
        "per_repo_cap": cap,
        "manifest_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    (out / "counts.json").write_text(json.dumps(counts, indent=1))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--split", "--test-set", "--dates", "--out", "--teacher-dir", "--old-manifest",
                 "--old-dir", "--earlier-pool"):  # fmt: skip
        parser.add_argument(flag, type=Path, required=True)
    parser.add_argument("--cap", type=int, required=True)
    args = parser.parse_args()
    held = {row if isinstance(row, str) else row["task"]
            for row in json.loads(args.test_set.read_text())["test"]}  # fmt: skip
    held |= later_candidate_ids(json.loads(args.split.read_text()))
    passes = new_repo_passes(args.teacher_dir) + old_passes(args.old_manifest, args.old_dir)
    allowed, refused = refuse(passes, held)
    pool = set(json.loads(args.earlier_pool.read_text()))
    allowed, outside = outside_earlier_pool(allowed, pool)
    kept = capped(allowed, json.loads(args.dates.read_text()), args.cap)
    counts = {"test_or_later_candidate": refused, "outside_earlier_pool": outside}
    print(json.dumps(write(args.out, kept, counts, args.cap), indent=1))


if __name__ == "__main__":
    main()
