"""Exploratory, after round 3: the meta-train items in their own training wording, as items and
judge queries in the round-3 bundle (`trained-items.jsonl`, `trained-queries.jsonl`), so one GPU
pass gives the clean contrast for `plug_r3_after.py` (trained lessons, trained wording).

Usage: uv run python scripts/routea/plug_r3_trained.py --pool P --plan PLAN --habit-split S --work B
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_r3_run import checked_splits, write_items  # noqa: E402
from plug_situation import build_items  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--pool", "--plan", "--habit-split", "--work"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    _, _, splits, _ = checked_splits(args)
    meta = [lesson for lessons in splits["meta"].values() for lesson in lessons]
    items = build_items(splits["meta"], meta)  # the exact items the training rows came from
    write_items(args.work, "trained", items, meta)
    print(json.dumps({"items": len(items), "queries": len(items) * 10}))


if __name__ == "__main__":
    main()
