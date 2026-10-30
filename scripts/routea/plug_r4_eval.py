"""Plug round 4's single-change exploration on round 3's 40 scored repos (now validation): bundles
for the 5080 and one readout against round 3's judge.

Usage: uv run python scripts/routea/plug_r4_eval.py bundle --work R3 --spark S --pool P
Usage:   --habit-rows H --out O
Usage: uv run python scripts/routea/plug_r4_eval.py score --work R3 --out O --results F

Every row's threshold is fitted the same way on the same 330 items (`plug_r4.operating_point`),
so coverage is compared at the same safety. A variant whose score files are not back yet reads
"not run", never a number.
"""

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4 import near_miss_rows, nightly_rows, operating_point, rewrite_queries  # noqa: E402
from plug_r4_rich import rich_bundle  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

HABIT_SHARES = (0.10, 0.25)  # the owner's two replay shares
R3_THRESHOLD = 0.99  # amendment 1's judge threshold, for the near-miss "yes" rows


def accepted(path: Path, field: str) -> dict:
    """lesson id -> accepted Spark text from one job's JSONL; rejected rows are counted out."""
    rows = _read_jsonl(path)
    return {row["lesson_id"]: row[field] for row in rows if field in row}


def slug(repo: str) -> str:
    """A repository as a directory name."""
    return repo.replace("/", "__")


def nightly_bundles(args: argparse.Namespace, items: list, repo_of: dict) -> dict:
    """Per repository and habit share: train rows from fixed-base nights, and its queries."""
    invented = accepted(args.spark / "invent-val40.jsonl", "situations")
    val_items, _ = load_items(args.work, "validation")
    val_scores = seed_mean_scores(
        [args.work / "scores" / f"validation-judge-s{s}.jsonl" for s in range(3)]
    )
    misses = near_miss_rows(val_items, val_scores, R3_THRESHOLD)
    habits = _read_jsonl(args.habit_rows)
    queries = {r["question_id"]: r for r in _read_jsonl(args.work / "scored-queries.jsonl")}
    sizes = {}
    for repo in sorted(set(repo_of.values())):
        picks = [i for i in items if repo_of[i.item_id] == repo and i.applies is not None]
        base = nightly_rows(picks, invented, misses)
        mine = [q for q in queries.values() if repo_of[q["question_id"].split("::")[0]] == repo]
        _jsonl(args.out / "nightly" / "queries" / f"{slug(repo)}.jsonl", mine)
        for share in HABIT_SHARES:
            rows = with_habits(base, habits, share)
            folder = args.out / "nightly" / f"habits{round(share * 100)}" / slug(repo)
            _jsonl(folder / "train.jsonl", rows)
            _jsonl(folder / "valid.jsonl", rows[:8])
            sizes[f"{slug(repo)}:{share}"] = len(rows)
    return {"near_miss_rows": len(misses), "nightly_rows": sizes}


def with_habits(rows: list[dict], habits: list[dict], share: float) -> list[dict]:
    """The rows plus habit rows (sampled with replacement) making up `share` of the total."""
    needed = round(len(rows) * share / (1 - share))
    rng = random.Random(0)
    mixed = rows + [rng.choice(habits) for _ in range(needed)]
    rng.shuffle(mixed)
    return mixed


def bundle(args: argparse.Namespace) -> dict:
    """The rewrite queries, the per-repo nightly bundles and the rich-situation bundle."""
    items, repo_of = load_items(args.work, "scored")
    rewrites = accepted(args.spark / "rewrite.jsonl", "text")
    _jsonl(args.out / "rewrite-queries.jsonl", rewrite_queries(items, rewrites))
    found = {"rewrites": len(rewrites), **nightly_bundles(args, items, repo_of)}
    found["rich"] = rich_bundle(args.pool, args.work, args.out / "rich", args.habit_rows)
    return found


def scores_or_none(paths: list[Path]) -> dict | None:
    """The seed-mean P(yes) of the files, or None if any file is missing."""
    return seed_mean_scores(paths) if all(path.exists() for path in paths) else None


def nightly_scores(folder: Path) -> dict | None:
    """One habit share's per-repo score files joined, or None if the share has not run."""
    paths = sorted(folder.glob("*.jsonl")) if folder.exists() else []
    if not paths:
        return None
    joined: dict[str, float] = {}
    for path in paths:
        joined.update(seed_mean_scores([path]))
    return joined


def variant_scores(work: Path, out: Path) -> dict[str, dict | None]:
    """Each row's P(yes) on the 330 items, or None when it has not run."""
    r3 = [work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)]
    mine = out / "scores"
    return {
        "round3_judge_3_seeds": scores_or_none(r3),
        "round3_judge_seed0": scores_or_none(r3[:1]),
        "rewritten_lessons": scores_or_none([mine / f"rewrite-judge-s{s}.jsonl" for s in range(3)]),
        "rich_situations_seed0": scores_or_none([mine / "rich-judge-s0.jsonl"]),
        "five_seeds": scores_or_none(r3 + [mine / f"scored-judge-s{s}.jsonl" for s in (3, 4)]),
        "judge_3b_tuned_seed0": scores_or_none([mine / "scored-3b-s0.jsonl"]),
        **{
            f"nightly_habits{round(share * 100)}_seed0": nightly_scores(
                mine / f"nightly-habits{round(share * 100)}"
            )
            for share in HABIT_SHARES
        },
    }


def habit_rates(out: Path) -> dict[str, float]:
    """Each habits file's hit rate (name -> rate)."""
    found = {}
    for path in sorted((out / "habits").glob("*.jsonl")) if (out / "habits").exists() else []:
        rows = _read_jsonl(path)
        found[path.stem] = round(sum(row["hit"] for row in rows) / len(rows), 4)
    return found


def score(args: argparse.Namespace) -> dict:
    """Every row's operating point on the same items, and the habit rates."""
    items, _ = load_items(args.work, "scored")
    rich_items, _ = load_items(args.out / "rich", "scored")
    rows = {}
    for name, scores in variant_scores(args.work, args.out).items():
        on = rich_items if name.startswith("rich") else items
        rows[name] = {"status": "not run"} if scores is None else operating_point(on, scores)
    return {
        "status": "exploratory, round 3's 40 scored repos as validation, no prereg",
        "rows": rows,
        "habits": habit_rates(args.out),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    one = stages.add_parser("bundle")
    for flag in ("--work", "--spark", "--pool", "--habit-rows", "--out"):
        one.add_argument(flag, type=Path, required=True)
    two = stages.add_parser("score")
    for flag in ("--work", "--out", "--results"):
        two.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "bundle":
        print(json.dumps(bundle(args), indent=1)[:2000])
        return
    found = score(args)
    args.results.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found["rows"], indent=1))


if __name__ == "__main__":
    main()
