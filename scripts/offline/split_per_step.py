"""Keep the published offline-selection result small: per-step arrays live outside the repo.

Violation prevented: **Leaky Narrative** at the repo boundary (QG-SEC-03 caps a tracked file at
1 MB; a 1.2 MB block of per-step bit strings is run output, not a summary) without a **Silent
Fallback**: the summary keeps a pointer (path, sha256, row counts) so a reader cannot mistake
"per-step moved" for "per-step missing", and `verify` proves no summary value changed.

    split_per_step.py split --src OLD.json --summary results/offline-selection.json
        --per-step data/offline/offline-selection-per-step.json
        --log data/offline/offline-selection.log
    split_per_step.py verify --old OLD.json --new results/offline-selection.json
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

POINTER_KEY = "per_step_file"
RUN_KEY = "run"
ADDED_KEYS = frozenset([POINTER_KEY, RUN_KEY])


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer_to(per_step: dict[str, list], path: str, written: Path) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": sha256_of(written),
        "arms": sorted(per_step),
        "rows_per_arm": {arm: len(rows) for arm, rows in per_step.items()},
        "note": "git-ignored; the run host copy is the original",
    }


def split(
    document: dict[str, Any], per_step_path: str, written: Path, run: dict[str, Any]
) -> dict[str, Any]:
    """Summary = every key except per_step, in the original order, plus the run and pointer keys."""
    per_step = document["per_step"]
    summary = {k: v for k, v in document.items() if k != "per_step"}
    summary[RUN_KEY] = run
    summary[POINTER_KEY] = pointer_to(per_step, per_step_path, written)
    return summary


def changed_values(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Keys whose serialized value differs; per_step is out of the comparison by design."""
    kept = [k for k in old if k != "per_step"]
    problems = [k for k in kept if json.dumps(old[k], indent=1) != json.dumps(new.get(k), indent=1)]
    unexpected = sorted(set(new) - set(kept) - ADDED_KEYS)
    return problems + [f"unexpected key {k}" for k in unexpected]


def load_per_step(summary_path: Path, root: Path) -> dict[str, list]:
    pointer = json.loads(summary_path.read_text())[POINTER_KEY]
    target = root / pointer["path"]
    if sha256_of(target) != pointer["sha256"]:
        raise ValueError(f"{target} does not match the sha256 recorded in {summary_path}")
    return json.loads(target.read_text())


def _run_section(src: dict[str, Any], log_path: Path) -> dict[str, Any]:
    return {
        "started_utc": "2026-10-27T19:24:26+00:00",
        "finished_utc": src["finished_utc"],
        "wall_clock_s": src["wall_clock_s"],
        "code_checksum_match": "not recorded in the run log",
        "log_file": {
            "path": "data/offline/offline-selection.log",
            "sha256": sha256_of(log_path),
            "note": "git-ignored",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    splitter = sub.add_parser("split")
    for flag in ("--src", "--summary", "--per-step", "--log"):
        splitter.add_argument(flag, required=True)
    verifier = sub.add_parser("verify")
    verifier.add_argument("--old", required=True)
    verifier.add_argument("--new", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "verify":
        bad = changed_values(
            json.loads(Path(args.old).read_text()), json.loads(Path(args.new).read_text())
        )
        print("\n".join(bad) or "summary values byte-identical")
        return 1 if bad else 0
    src = json.loads(Path(args.src).read_text())
    target = Path(args.per_step)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(src["per_step"], indent=1))
    summary = split(src, args.per_step, target, _run_section(src, Path(args.log)))
    Path(args.summary).write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
