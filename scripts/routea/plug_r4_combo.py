"""Plug round 4 combo pass: nightly per-repo adapters + rich input + merged twins.

Usage: uv run python scripts/routea/plug_r4_combo.py bundle --work R3 --r4 R4 --spark S --out O
Usage: uv run python scripts/routea/plug_r4_combo.py readout --r4 R4 --combo O --results F

A twin pick (same failed command and error as the lesson) is right, so negatives exclude twins.
"""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge import JUDGE_SYSTEM  # noqa: E402
from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4 import near_miss_rows, nightly_rows  # noqa: E402
from plug_r4_combine import best_safe, candidates, cross_validated, forms, read_at  # noqa: E402
from plug_r4_eval import R3_THRESHOLD, accepted, slug, with_habits  # noqa: E402
from plug_r4_rich import with_tail  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

SHARES = (0.10, 0.40)  # 10% is the explored setting; 40% is tried on a few repos only
FEW_REPOS = 5
SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
OUTPUT_MARK = "\nOutput:\n"


def tail_of(situation: str) -> str:
    """The output tail a rich situation carries."""
    return situation.split(OUTPUT_MARK, 1)[1]


def twins_of(item, universe: dict) -> tuple[str, ...]:
    """Ids of the other lessons with the same failed command and error line as the item's own."""
    own = item.applies
    return tuple(
        x.lesson_id
        for x in universe.values()
        if x.lesson_id != own.lesson_id and (x.failed, x.error) == (own.failed, own.error)
    )


def habit_rows_of(nightly: Path) -> list[dict]:
    """The habit-replay rows already in round 4's nightly bundles (not judge rows)."""
    seen: dict[str, dict] = {}
    for path in sorted(nightly.glob("habits10/*/train.jsonl")):
        for row in _read_jsonl(path):
            if row["messages"][0]["content"] != JUDGE_SYSTEM:
                seen[json.dumps(row, sort_keys=True)] = row
    return list(seen.values())


def rich_nights(picks: list, universe: dict, invented: dict, misses: list[dict]) -> list[dict]:
    """One repository's night: invented situations with their real output tails, twins kept out
    of the negatives, near-misses added."""
    rich_invented = {
        i.applies.lesson_id: [
            with_tail(s, tail_of(i.situation)) for s in invented.get(i.applies.lesson_id, [])
        ]
        for i in picks
    }
    no_twins = [replace(i, excused=i.excused + twins_of(i, universe)) for i in picks]
    return nightly_rows(no_twins, rich_invented, misses)


def write_bundle(folder: Path, rows: list[dict]) -> None:
    """A training folder: the rows and the first eight as validation."""
    _jsonl(folder / "train.jsonl", rows)
    _jsonl(folder / "valid.jsonl", rows[:8])


def shares_for(number: int) -> tuple[float, ...]:
    """The habit shares a repository gets: 10% for all, 40% only for the first few."""
    return SHARES if number < FEW_REPOS else SHARES[:1]


def repo_queries(queries: list[dict], repo_of: dict, repo: str) -> list[dict]:
    """The scored queries of one repository."""
    return [q for q in queries if repo_of[q["question_id"].split("::")[0]] == repo]


def bundle(args: argparse.Namespace) -> dict:
    """Per repo and share: rich nightly training rows; queries are copied per repo."""
    items, repo_of = load_items(args.r4 / "rich", "scored")
    universe = {x.lesson_id: x for i in items for x in i.prompt_lessons}
    invented = accepted(args.spark / "invent-val40.jsonl", "situations")
    val_items, _ = load_items(args.work, "validation")
    paths = [args.work / "scores" / f"validation-judge-s{s}.jsonl" for s in range(3)]
    misses = near_miss_rows(val_items, seed_mean_scores(paths), R3_THRESHOLD)
    habits = habit_rows_of(args.r4 / "nightly")
    queries = _read_jsonl(args.r4 / "rich" / "scored-queries.jsonl")
    repos = sorted(set(repo_of.values()))
    written = 0
    for number, repo in enumerate(repos):
        picks = [i for i in items if repo_of[i.item_id] == repo and i.applies is not None]
        base = rich_nights(picks, universe, invented, misses)
        _jsonl(args.out / "queries" / f"{slug(repo)}.jsonl", repo_queries(queries, repo_of, repo))
        for share in shares_for(number):
            folder = args.out / f"habits{round(share * 100)}" / slug(repo)
            write_bundle(folder, with_habits(base, habits, share))
            written += 1
    return {"habit_rows": len(habits), "near_miss_rows": len(misses), "bundles": written}


def merged_candidates(items, cands) -> dict:
    """The shortlists with each twin of an item's own lesson renamed to that lesson, so a twin
    pick is right (merged twins: the true fix is among the listed fixes)."""
    universe = {x.lesson_id: x for i in items for x in i.prompt_lessons}
    merged = {}
    for item in items:
        rename = {}
        if item.applies is not None:
            rename = {t: item.applies.lesson_id for t in twins_of(item, universe)}
        merged[item.item_id] = [(rename.get(a, a), b, c) for a, b, c in cands[item.item_id]]
    return merged


def joined_scores(folder: Path, scale: str) -> dict | None:
    """One share's per-repo P(yes) at one scale, joined; None if no repo has it."""
    paths = sorted(folder.glob(f"*/s{scale}/scores.jsonl"))
    if not paths:
        return None
    joined: dict[str, float] = {}
    for path in paths:
        joined.update({r["question_id"]: r["p_yes"] for r in _read_jsonl(path)})
    return joined


def habit_mean(folder: Path, scale: str) -> float | None:
    """Mean habit hit rate across the repos' adapters at one scale."""
    rates = []
    for path in sorted(folder.glob(f"*/s{scale}/habits.jsonl")):
        rows = _read_jsonl(path)
        rates.append(sum(r["hit"] for r in rows) / len(rows))
    return round(sum(rates) / len(rates), 4) if rates else None


def readout_one(items, repo_of, scores) -> dict:
    """Judge alone and the two-threshold rule, in sample and cross-validated, twins merged."""
    cands = merged_candidates(items, candidates(items, scores))
    out = {"items": len(items)}
    for form in ("judge_alone", "two_d_threshold"):
        rules, grid = forms(items, cands)[form]
        out[form] = {
            "in_sample": read_at(items, cands, rules, best_safe(items, cands, rules, grid)),
            "cross_validated": cross_validated(items, repo_of, cands, form),
        }
    return out


def readout(args: argparse.Namespace) -> dict:
    """Every share and scale: the two rules' rates and the habit mean."""
    items, repo_of = load_items(args.r4 / "rich", "scored")
    found = {}
    for folder in sorted(args.combo.glob("scores-habits*")):
        share = folder.name.removeprefix("scores-")
        for scale in sorted(
            {p.parent.name[1:] for p in folder.glob("*/s*/scores.jsonl")}, key=float
        ):
            scores = joined_scores(folder, scale)
            repos = {p.parent.parent.name for p in folder.glob(f"*/s{scale}/scores.jsonl")}
            kept = [i for i in items if i.item_id in {k.split("::")[0] for k in scores}]
            found[f"{share}@{scale}"] = {
                "repos": len(repos),
                "habits": habit_mean(folder, scale),
                **readout_one(kept, repo_of, scores),
            }
    return {"status": "exploratory combo, round 3's 40 scored repos as validation", "rows": found}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    one = stages.add_parser("bundle")
    for flag in ("--work", "--r4", "--spark", "--out"):
        one.add_argument(flag, type=Path, required=True)
    two = stages.add_parser("readout")
    for flag in ("--r4", "--combo", "--results"):
        two.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "bundle":
        print(json.dumps(bundle(args)))
        return
    found = readout(args)
    args.results.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found["rows"], indent=1)[:3000])


if __name__ == "__main__":
    main()
