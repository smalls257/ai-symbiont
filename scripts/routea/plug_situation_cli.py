"""Plug situation test, the stages that read and write files: build, narrow, ranker, score, report.

Usage: uv run python scripts/routea/plug_situation_cli.py build --pool P --test-repos PLAN --work W
Usage: uv run python scripts/routea/plug_situation_cli.py score --work W --arms a1 a2v --out F
Usage: uv run python scripts/routea/plug_situation_cli.py narrow --source W --keep 5 --work W5
Usage: uv run python scripts/routea/plug_situation_cli.py pilot-report --source W --work W5 --arms A
Usage: uv run python scripts/routea/plug_situation_cli.py ranker-answers --work W5 [--source W]

The pure parts (items, ranker, scorer) live in `plug_situation.py`; this module reads the pool and
writes items, answers and reports. A build refuses any item whose own correct note would not score.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug import distinct  # noqa: E402
from plug_situation import (  # noqa: E402
    Item,
    build_items,
    item_from,
    item_record,
    key_of,
    narrowed,
    own_note_misses,
    pick_item_abstention,
    ranker_answer,
    ranker_recall,
    rates,
    shows_applicable,
)
from warm_start import _jsonl, _read_jsonl, paired_gain  # noqa: E402


def build(pool: Path, test_repos: list[str], out: Path) -> dict:
    """Items for the given test repos, distractors from every other repo's lessons."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    candidates, _, _ = build_lessons._candidates(pool, [])
    by_repo = distinct(candidates)
    test = {repo: by_repo[repo] for repo in test_repos}
    others = [lesson for repo, items in by_repo.items() if repo not in test for lesson in items]
    items = build_items(test, others)
    _jsonl(
        out / "items.jsonl", [item_record(item) | {"repo": _repo_of(item, test)} for item in items]
    )
    silent = sum(item.applies is None for item in items)
    misses = own_note_misses(items)
    if misses:
        raise ValueError(f"{misses} pick items would score their own correct note as a miss")
    (out / "collisions.json").write_text(json.dumps(collisions(test, others, items), indent=1))
    return {
        "items": len(items),
        "silence_items": silent,
        "repos": len(test),
        "distractor_pool": len(others),
    }


def collisions(
    test: dict[str, list[Lesson]], pool: Sequence[Lesson], items: Sequence[Item]
) -> dict:
    """Per repo: pool lessons kept out for sharing a test lesson's key, and lessons excused."""
    found = {}
    for repo, lessons in sorted(test.items()):
        keys = {key_of(lesson) for lesson in lessons}
        shared = sum(1 for other in pool if other.repo != repo and key_of(other) in keys)
        mine = {lesson.lesson_id for lesson in lessons}
        excused = sum(len(i.excused) for i in items if i.applies and i.applies.lesson_id in mine)
        found[repo] = {
            "shared_key_distractors_kept_out": shared,
            "excused_in_pick_prompts": excused,
        }
    return found


def _repo_of(item: Item, test: dict[str, list[Lesson]]) -> str:
    lesson_id = item.item_id.rsplit("-", 1)[0]
    return next(
        repo for repo, items in test.items() if any(i.lesson_id == lesson_id for i in items)
    )


def score(work: Path, arms: list[str]) -> dict:
    """Per arm: mean rates over repos with a bootstrap interval, and per-repo rates."""
    records = _read_jsonl(work / "items.jsonl")
    by_repo: dict[str, list[Item]] = {}
    for record in records:
        by_repo.setdefault(record["repo"], []).append(item_from(record))
    rows, per_repo = [], []
    for arm in arms:
        rows_of = _read_jsonl(work / "answers" / f"{arm}.jsonl")
        answers = {row["question_id"]: row["answer"] for row in rows_of}
        found = {repo: rates(items, answers) for repo, items in sorted(by_repo.items())}
        row = {"arm": arm, "repos": len(found)}
        for measure in ("pick", "useful", "wrong_pick", "silence"):
            interval = paired_gain([cell[measure] for cell in found.values()])
            row[measure] = interval["mean_gain"]
            row[f"{measure}_ci95"] = [interval["ci95_low"], interval["ci95_high"]]
        rows.append(row)
        per_repo.extend({"arm": arm, "repo": repo, **cell} for repo, cell in found.items())
    return {"rows": rows, "per_repo_rows": per_repo}


def pilot_report(full: Path, top: Path, arms: list[str]) -> dict:
    """The pilot's results: both prompt sizes, the ranker, and pick-item abstention per arm."""
    full_items = [item_from(r) for r in _read_jsonl(full / "items.jsonl")]
    top_items = [item_from(r) for r in _read_jsonl(top / "items.jsonl")]
    report = {
        "ranker": ranker_recall(full_items),
        "prompt_60": score(full, arms),
        "top_5": score(top, arms),
    }
    for label, work, items in (("prompt_60", full, full_items), ("top_5", top, top_items)):
        for arm in arms:
            answers = {
                r["question_id"]: r["answer"]
                for r in _read_jsonl(work / "answers" / f"{arm}.jsonl")
            }
            report[label][f"{arm}_pick_item_abstention"] = pick_item_abstention(items, answers)
    report["answer_scripts_sha256"] = (top / "answerer.sha256s").read_text().split()[::2]
    report["collisions"] = json.loads((full / "collisions.json").read_text())
    report["own_note_misses"] = {
        "prompt_60": own_note_misses(full_items),
        "top_5": own_note_misses(top_items),
    }
    report["status"] = "exploratory pilot on the 10 validation repos, no prereg"
    return report


def _emit(document: dict, out: Path | None) -> None:
    text = json.dumps(document, indent=1, sort_keys=True)
    if out:
        out.write_text(text + "\n")
    print(text)


def _stage_build(args: argparse.Namespace) -> None:
    repos = sorted(json.loads(args.test_repos.read_text())["test_repos"])
    print(json.dumps(build(args.pool, repos, args.work), indent=1))


def _stage_narrow(args: argparse.Namespace) -> None:
    records = _read_jsonl(args.source / "items.jsonl")
    rows = [item_record(narrowed(item_from(r), args.keep)) | {"repo": r["repo"]} for r in records]
    _jsonl(args.work / "items.jsonl", rows)
    kept = sum(1 for row in rows if shows_applicable(row))
    print(json.dumps({"items": len(rows), "applicable_kept": kept}))


def _stage_ranker(args: argparse.Namespace) -> None:
    # The ranker-alone row answers from the full prompt's ranking, even for narrowed items.
    ranked_from = args.source or args.work
    rows = [
        {"question_id": r["question_id"], "answer": ranker_answer(item_from(r))}
        for r in _read_jsonl(ranked_from / "items.jsonl")
    ]
    _jsonl(args.work / "answers" / "ranker.jsonl", rows)
    print(json.dumps({"answers": len(rows), "ranked_from": ranked_from.name}))


STAGES = {
    "build": _stage_build,
    "narrow": _stage_narrow,
    "ranker-answers": _stage_ranker,
    "score": lambda args: _emit(score(args.work, args.arms), args.out),
    "pilot-report": lambda args: _emit(pilot_report(args.source, args.work, args.arms), args.out),
}


def main() -> None:
    """Run one stage; see the module docstring for each stage's arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--source", type=Path, help="work dir whose items `narrow` reads")
    parser.add_argument("--keep", type=int, default=5, help="lessons the ranker passes on")
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--test-repos", type=Path, help="plan.json whose test_repos are tested")
    parser.add_argument("--arms", nargs="+", default=[])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    STAGES[args.stage](args)


if __name__ == "__main__":
    main()
