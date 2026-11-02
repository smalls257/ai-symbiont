"""Plug round 3's runner (prereg/2026-10-29-plug-judge.md): bundle, check and the validation fit.

Usage: uv run python scripts/routea/plug_r3_run.py bundle --pool P --plan PLAN --habit-split S
Usage:   --habit-rows H --out B
Usage: uv run python scripts/routea/plug_r3_run.py check --pool P --habit-rows H --aidev-lessons L
Usage:   --prereg prereg/2026-10-29-plug-judge.md --work B
Usage: uv run python scripts/routea/plug_r3_run.py fit --work B --judge S0 S1 S2 --untrained U
The scored stage is `plug_r3_score.py`; it refuses to run without this stage's selection.json.
"""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug import distinct  # noqa: E402
from plug_judge import choose, judge_mix, judge_queries, outcome_rates  # noqa: E402
from plug_judge_cli import GRID, SHORTLIST, seed_mean_scores  # noqa: E402
from plug_r2_backend import iters_for  # noqa: E402
from plug_r2_rows import PHRASINGS, phrase  # noqa: E402
from plug_r2_score import check, check_plan  # noqa: E402
from plug_r3 import (  # noqa: E402
    PREREG_NAME,
    RANKER_GRID,
    SEEN_WORDING,
    check_meta,
    check_splits,
    fit_lowest,
    meta_keys,
    per_repo,
    ranker_choices,
    reworded,
    round3_splits,
    source_of,
    top_score_range,
)
from plug_r3_decide import power  # noqa: E402
from plug_situation import Item, build_items, item_from, item_record, narrowed  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

EPOCHS = 3  # the round-2 recipe
TOP5 = 5  # the plain-1B floor reads round 2's top-5 prompt


def checked_splits(args: argparse.Namespace) -> tuple[dict, dict, dict, dict]:
    """Lessons by repo, the plan, the three splits and the shared-key counts; raises on a plan,
    meta-train list or overlap the prereg did not fix."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    candidates, _, _ = build_lessons._candidates(args.pool, [])
    by_repo = distinct(candidates)
    plan = json.loads(args.plan.read_text())
    check_plan(plan)
    splits = round3_splits(by_repo, plan)
    check_meta(splits)
    habit_repos = [r for r, s in json.loads(args.habit_split.read_text()).items() if s == "train"]
    return by_repo, plan, splits, check_splits(splits, habit_repos)


def bundle(args: argparse.Namespace) -> dict:
    """Training rows, items and judge queries for every split. The counts it returns are the ones
    the prereg pins."""
    by_repo, plan, splits, shared = checked_splits(args)
    meta = [lesson for lessons in splits["meta"].values() for lesson in lessons]
    meta_items = build_items(splits["meta"], meta)
    phrasings = [partial(phrase, template) for template in PHRASINGS]
    mix = judge_mix(meta_items, SHORTLIST, phrasings, source_of(meta), _read_jsonl(args.habit_rows))
    _jsonl(args.out / "rows" / "train.jsonl", mix["rows"])
    _jsonl(args.out / "rows" / "valid.jsonl", mix["rows"][:8])
    items = {
        name: build_items(splits[name], others(by_repo, splits[name]))
        for name in ("validation", "scored")
    }
    items["seen"] = reworded(meta_items, meta, SEEN_WORDING)
    for name, found in items.items():
        lessons = meta if name == "seen" else [x for v in splits[name].values() for x in v]
        write_items(args.out, name, found, lessons)
    write_meta(args.out, splits, plan)
    return {
        **mix["counts"],
        "iters": iters_for(mix["counts"]["total"], EPOCHS),
        "shared_keys_with_meta": shared,
        "repos": {name: len(split) for name, split in splits.items()},
        "items": {name: len(found) for name, found in items.items()},
        "validation_top_score_range": top_score_range(items["validation"]),
    }


def others(by_repo: dict, held: dict) -> list:
    """Distractors for held repos: every other repo's lessons, meta-train ones included."""
    return [lesson for repo, lessons in by_repo.items() if repo not in held for lesson in lessons]


def write_items(out: Path, name: str, items: list[Item], lessons: list) -> None:
    """The split's items with their repo, their judge queries and, for scored, the top-5 items."""
    source = source_of(lessons)
    records = [item_record(item) | {"repo": source(item).repo} for item in items]
    _jsonl(out / f"{name}-items.jsonl", records)
    _jsonl(out / f"{name}-queries.jsonl", judge_queries(items, SHORTLIST))
    if name == "scored":
        top = [
            item_record(narrowed(item, TOP5)) | {"repo": record["repo"]}
            for item, record in zip(items, records, strict=True)
        ]
        _jsonl(out / "scored-top5.jsonl", top)


def write_meta(out: Path, splits: dict, plan: dict) -> None:
    """The plan (for `check`), and meta-train's lesson ids and failure keys (for `score`)."""
    (out / "plan.json").write_text(json.dumps(plan, indent=1, sort_keys=True))
    ids = sorted(x.lesson_id for v in splits["meta"].values() for x in v)
    keys = sorted([kind, list(tokens)] for kind, tokens in meta_keys(splits))
    (out / "meta.json").write_text(json.dumps({"lesson_ids": ids, "keys": keys}, indent=1))


def load_items(work: Path, name: str) -> tuple[list[Item], dict[str, str]]:
    """A split's items and each item's repo, as `bundle` wrote them."""
    records = _read_jsonl(work / f"{name}-items.jsonl")
    return [item_from(r) for r in records], {r["question_id"]: r["repo"] for r in records}


def judged(items: list[Item], scores: dict[str, float], threshold: float) -> list:
    """The judge's choices at a threshold over the ranker's shortlist."""
    return choose(items, scores, SHORTLIST, threshold)


def fit(args: argparse.Namespace) -> dict:
    """Thresholds on all 10 validation repos, per-seed thresholds, the ranker's grid coverage and
    the MDE: the validation amendment's numbers, written before any scored answer."""
    items, repo_of = load_items(args.work, "validation")
    ensemble = seed_mean_scores(args.judge)
    candidates = {
        "judge": (partial(judged, items, ensemble), GRID),
        "ranker_threshold": (partial(ranker_choices, items), RANKER_GRID),
        "untrained_1b": (partial(judged, items, seed_mean_scores([args.untrained])), GRID),
    }
    found = {row: fit_lowest(items, pick, grid) for row, (pick, grid) in candidates.items()}
    seeds = [
        fit_lowest(items, partial(judged, items, seed_mean_scores([p])), GRID) for p in args.judge
    ]
    rates = {
        row: outcome_rates(items, candidates[row][0](t))
        for row, t in found.items()
        if t is not None
    }
    return {
        "prereg": PREREG_NAME,
        "thresholds": found,
        "judge_seed_thresholds": seeds,
        "validation_rates": rates,
        "ranker_grid": [RANKER_GRID[0], RANKER_GRID[-1]],
        "validation_top_score_range": top_score_range(items),
        "power": validation_power(args.work, items, repo_of, candidates, found),
    }


def validation_power(
    work: Path, items: list, repo_of: dict, candidates: dict, found: dict
) -> dict | None:
    """The MDE on judge-minus-ranker validation gains; None if either has no safe point."""
    if found["judge"] is None or found["ranker_threshold"] is None:
        return None
    cells = {
        row: per_repo(items, candidates[row][0](found[row]), repo_of)
        for row in ("judge", "ranker_threshold")
    }
    gains = [
        cells["judge"][r]["pick"] - cells["ranker_threshold"][r]["pick"]
        for r in sorted(cells["judge"])
    ]
    scored = [r for r in _read_jsonl(work / "scored-items.jsonl") if r["applies"] is not None]
    picks = [i for i in items if i.applies is not None]
    return power(
        gains, len(picks) / len(cells["judge"]), len(scored) / len({r["repo"] for r in scored})
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    one = stages.add_parser("bundle")
    for flag in ("--pool", "--plan", "--habit-split", "--habit-rows", "--out"):
        one.add_argument(flag, type=Path, required=True)
    two = stages.add_parser("check")
    for flag in ("--pool", "--habit-rows", "--aidev-lessons", "--prereg", "--work"):
        two.add_argument(flag, type=Path, required=True)
    three = stages.add_parser("fit")
    three.add_argument("--work", type=Path, required=True)
    three.add_argument("--judge", type=Path, nargs=3, required=True)
    three.add_argument("--untrained", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "bundle":
        print(json.dumps(bundle(args), indent=1))
    elif args.stage == "check":
        print(json.dumps(check(args, expects=PREREG_NAME), indent=1))
    else:
        selection = fit(args)
        (args.work / "selection.json").write_text(json.dumps(selection, indent=1, sort_keys=True))
        print(json.dumps(selection, indent=1))


if __name__ == "__main__":
    main()
