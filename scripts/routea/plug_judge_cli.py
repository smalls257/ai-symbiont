"""Plug round 3's judge: build training rows and validation queries; score returned P(yes) values.

Usage: uv run python scripts/routea/plug_judge_cli.py bundle --pool P --plan PLAN --habit-split S
Usage:   --items V/items.jsonl --out B
Usage: uv run python scripts/routea/plug_judge_cli.py score --items V/items.jsonl --scores S --out F

Rows come from meta-train lessons only (the plan's scored and validation repos are held out,
`plug.check_unseen`). The silence threshold is fitted on the validation repos in the lower half by
name hash and reported on the other half and on all; the scored repos are never touched here.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug import distinct  # noqa: E402
from plug_judge import curve, fit_threshold, judge_queries, judge_rows  # noqa: E402
from plug_r2_rows import meta_split  # noqa: E402
from plug_round2 import name_hash  # noqa: E402
from plug_situation import build_items, item_from, ranker_recall  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

SHORTLIST = 10  # the ranker's top 10 hold the applicable lesson for every validation item
GRID = tuple(round(step / 100, 2) for step in range(0, 101, 5))


def bundle(args: argparse.Namespace) -> dict:
    """Training rows from meta-train items and judge queries for the validation items."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    candidates, _, _ = build_lessons._candidates(args.pool, [])
    habit_repos = [r for r, s in json.loads(args.habit_split.read_text()).items() if s == "train"]
    split = meta_split(distinct(candidates), json.loads(args.plan.read_text()), habit_repos)
    pool = [lesson for items in split.meta.values() for lesson in items]
    rows = judge_rows(build_items(split.meta, pool), SHORTLIST)
    _jsonl(args.out / "rows" / "train.jsonl", rows)
    _jsonl(args.out / "rows" / "valid.jsonl", rows[:8])
    items = [item_from(r) for r in _read_jsonl(args.items)]
    _jsonl(args.out / "queries.jsonl", judge_queries(items, SHORTLIST))
    return {
        "train_rows": len(rows),
        "queries": len(items) * SHORTLIST,
        "meta_repos": len(split.meta),
    }


def score(args: argparse.Namespace) -> dict:
    """Fit the threshold on half the validation repos; the curve on the other half and on all."""
    records = _read_jsonl(args.items)
    scores = {r["question_id"]: r["p_yes"] for r in _read_jsonl(args.scores)}
    repos = sorted({r["repo"] for r in records}, key=name_hash)
    fitting = set(repos[: len(repos) // 2])
    fit_items = [item_from(r) for r in records if r["repo"] in fitting]
    held_items = [item_from(r) for r in records if r["repo"] not in fitting]
    all_items = fit_items + held_items
    threshold = fit_threshold(fit_items, scores, SHORTLIST, GRID)
    return {
        "shortlist": SHORTLIST,
        "ranker": ranker_recall(all_items, depths=(1, 5, 10)),
        "fitting_repos": sorted(fitting),
        "fitting_items": len(fit_items),
        "threshold": threshold,
        "held_out_at_threshold": curve(held_items, scores, SHORTLIST, [threshold])[0],
        "curve_held_out": curve(held_items, scores, SHORTLIST, GRID),
        "curve_all": curve(all_items, scores, SHORTLIST, GRID),
    }


def main() -> None:
    """Run one stage."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("bundle", "score"))
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--habit-split", type=Path)
    parser.add_argument("--items", type=Path, required=True, help="validation items (full prompt)")
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = bundle(args) if args.stage == "bundle" else score(args)
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.stage == "score":
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
