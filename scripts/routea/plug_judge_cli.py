"""Plug round 3's judge: build training rows and validation queries; score returned P(yes) values.

Usage: uv run python scripts/routea/plug_judge_cli.py bundle --pool P --plan PLAN --habit-split S
Usage:   --items V/items.jsonl --out B
Usage: uv run python scripts/routea/plug_judge_cli.py score --items V --scores S0 S1 S2 --out F
Usage: uv run python scripts/routea/plug_judge_cli.py v2-queries --items TOP5 --answers A.. --out D
Usage: uv run python scripts/routea/plug_judge_cli.py v2-score --items TOP5 --answers A..
Usage:   --confidences C.. --out F

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
from plug_judge import (  # noqa: E402
    Choice,
    curve,
    fit_threshold,
    judge_queries,
    judge_rows,
    outcome_rates,
)
from plug_r2_rows import meta_split  # noqa: E402
from plug_round2 import name_hash  # noqa: E402
from plug_situation import build_items, item_from, lexical_rank, ranker_recall  # noqa: E402
from plug_v2conf import fit_seed_threshold, named_lesson, note_queries, seed_curve  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

SHORTLIST = 10  # the ranker's top 10 hold the applicable lesson for every validation item
# P(yes) thresholds: 0.01 steps, finer near 1 where the judges separate. Refined after the first
# coarse grid (0.05 steps) was seen to jump past every safe point (exploratory, disclosed).
GRID = tuple(round(step / 100, 2) for step in range(101)) + tuple(
    round(0.99 + k / 1000, 3) for k in range(1, 10)
)


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


def seed_mean_scores(paths: list[Path]) -> dict[str, float]:
    """P(yes) per query averaged over seed files; raises if the files cover different queries."""
    files = [{r["question_id"]: r["p_yes"] for r in _read_jsonl(path)} for path in paths]
    keys = set(files[0])
    if any(set(found) != keys for found in files[1:]):
        raise ValueError("seed score files cover different queries")
    return {key: sum(found[key] for found in files) / len(files) for key in keys}


def score(args: argparse.Namespace) -> dict:
    """Fit the threshold on half the validation repos; the curve on the other half and on all."""
    records = _read_jsonl(args.items)
    scores = seed_mean_scores(args.scores)
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


def _answers(path: Path) -> dict[str, str]:
    return {r["question_id"]: r["answer"] for r in _read_jsonl(path)}


def v2_queries(args: argparse.Namespace) -> dict:
    """One note-scoring file per V2 seed, from that seed's answers on the top-5 items."""
    items = [item_from(r) for r in _read_jsonl(args.items)]
    counts = {}
    for seed, path in enumerate(args.answers):
        rows = note_queries(items, _answers(path))
        _jsonl(args.out / f"v2-notes-s{seed}.jsonl", rows)
        counts[f"s{seed}"] = len(rows)
    return counts


def v2_score(args: argparse.Namespace) -> dict:
    """V2 with a confidence threshold: fitted on the same validation repos as the judge."""
    records = _read_jsonl(args.items)
    if len(args.answers) != len(args.confidences):
        raise ValueError("one confidence file per answer file")
    seeds = [
        (_answers(a), {r["question_id"]: r["logprob"] for r in _read_jsonl(c)})
        for a, c in zip(args.answers, args.confidences, strict=True)
    ]
    repos = sorted({r["repo"] for r in records}, key=name_hash)
    fitting = set(repos[: len(repos) // 2])
    fit_items = [item_from(r) for r in records if r["repo"] in fitting]
    held_items = [item_from(r) for r in records if r["repo"] not in fitting]
    # Mean log-prob from -1 to 0 in 0.01 steps: V2's confidences all lie there. Refined after the
    # first grid (0.1 steps from -4) jumped past every safe point (exploratory, disclosed).
    grid = tuple(round(-1 + step / 100, 2) for step in range(101))
    threshold = fit_seed_threshold(fit_items, seeds, grid)
    return {
        "fitting_repos": sorted(fitting),
        "threshold": threshold,
        "held_out_at_threshold": seed_curve(held_items, seeds, [threshold])[0],
        "curve_held_out": seed_curve(held_items, seeds, grid),
        "curve_all": seed_curve(fit_items + held_items, seeds, grid),
    }


def references(args: argparse.Namespace) -> dict:
    """Ranker alone (its top-1 lesson, always answering) and plain 1B (round 2's floor answers on
    the top-5 prompt) on the held-out validation repos the judges are reported on."""
    records = _read_jsonl(args.items)
    repos = sorted({r["repo"] for r in records}, key=name_hash)
    fitting = set(repos[: len(repos) // 2])
    held = [item_from(r) for r in records if r["repo"] not in fitting]
    ranker = [Choice(i.item_id, lexical_rank(i)[0].lesson_id, 1.0) for i in held]
    top5 = {r["question_id"]: item_from(r) for r in _read_jsonl(args.top5)}
    held5 = [top5[i.item_id] for i in held]
    (floor,) = [_answers(path) for path in args.answers]
    plain = [Choice(i.item_id, named_lesson(i, floor[i.item_id]), 0.0) for i in held5]
    return {
        "held_out_items": len(held),
        "ranker_alone": outcome_rates(held, ranker),
        "plain_1b": outcome_rates(held5, plain),
    }


def combine(args: argparse.Namespace) -> dict:
    """One exploratory results document from each arm's score output (`name=path` pairs)."""
    document = {"status": "exploratory, validation repos only, no prereg", **references(args)}
    for pair in args.inputs:
        name, path = pair.split("=", 1)
        found = json.loads(Path(path).read_text())
        safe = [r for r in found["curve_all"] if r["silence"] >= 0.80 and r["wrong_pick"] <= 0.05]
        best = max(safe, key=lambda row: row["pick"]) if safe else None
        document[name] = {**found, "best_safe_point_all": best}
    return document


def main() -> None:
    """Run one stage."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("bundle", "score", "v2-queries", "v2-score", "combine"))
    parser.add_argument("--inputs", nargs="+", help="combine: name=path of each score output")
    parser.add_argument("--top5", type=Path, help="combine: the top-5 validation items")
    parser.add_argument("--answers", type=Path, nargs="+", help="V2's answer files, one per seed")
    parser.add_argument("--confidences", type=Path, nargs="+", help="V2 note log-probs per seed")
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--habit-split", type=Path)
    parser.add_argument("--items", type=Path, help="validation items (full prompt)")
    parser.add_argument("--scores", type=Path, nargs="+", help="one P(yes) file per seed")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stages = {
        "bundle": bundle,
        "score": score,
        "v2-queries": v2_queries,
        "v2-score": v2_score,
        "combine": combine,
    }
    result = stages[args.stage](args)
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.stage in ("score", "v2-score", "combine"):
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
