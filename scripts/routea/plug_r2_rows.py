"""Plug round 2 training rows per variant (prereg/2026-10-29-plug-situations.md, Variants).

Usage: uv run python scripts/routea/plug_r2_rows.py --variant V1 --pool P --plan PLAN
Usage:   --habit-split S --habit-rows H --aidev-lessons L --out DIR

Every variant trains from plain weights on the meta-train repos only (`plug.check_unseen` raises on
a shared repo or lesson). Situation rows are built as the test's items are: a 60-lesson prompt, the
ranker's top 5 shuffled per item. Rows too long for the window are dropped later by `fit_rows.py`.
"""

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from l2l_quick import ABSTAIN, MAX_ROW_CHARS, chat, meta_rows, row_chars  # noqa: E402
from lessons import Lesson  # noqa: E402
from plug import Split, check_unseen, distinct  # noqa: E402
from plug_situation import ASK, build_items, context_of, narrowed  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

# V4 (3B) trains on the current best variant's rows; it has no rows of its own.
VARIANTS = ("V1", "V2", "V3")
TOP = 5  # lessons the ranker passes to the reader
UNRELATED = 2  # V3: AIDev habit lessons added to each training prompt
SEED = 0
# V2's extra phrasings of a situation (fixed before V2 runs; never used in validation or scoring,
# which use `plug_situation.situation_of`). With the original, 15 phrasings per lesson.
PHRASINGS = (
    "Command `{failed}` just failed in {repo} while working on {file}: {error}",
    "In {repo}, running `{failed}` (touching {file}) gave: {error}",
    "The agent ran `{failed}` for {file} in {repo} and saw: {error}",
    "{repo}: `{failed}` failed. File: {file}. Error: {error}",
    "Working in {repo} on {file}. Last command `{failed}` returned an error: {error}",
    "Error from `{failed}` in {repo} ({file}): {error}",
    "While editing {file} in {repo}, `{failed}` stopped with: {error}",
    "Repo {repo}, file {file}: the command `{failed}` failed with {error}",
    "`{failed}` did not work in {repo}; it reported {error} (file {file})",
    "Just tried `{failed}` in {repo} for {file}. Output: {error}",
    "The run of `{failed}` on {file} in {repo} ended in an error: {error}",
    "{error}, after running `{failed}` in {repo} on {file}",
    "In the {repo} checkout, `{failed}` failed for {file} with {error}",
    "Attempted `{failed}` ({repo}, {file}); result: {error}",
)


def meta_split(by_repo: dict[str, list[Lesson]], plan: dict, habit_repos: list[str]) -> Split:
    """Meta-train repos: every repo neither scored nor validation; raises on any overlap."""
    held = set(plan["scored"]) | set(plan["validation"])
    test = {repo: by_repo[repo] for repo in sorted(held)}
    meta = {repo: items for repo, items in sorted(by_repo.items()) if repo not in held}
    split = Split(test, meta, {})
    check_unseen(split, habit_repos)
    return split


def phrase(template: str, lesson: Lesson) -> str:
    """One situation phrasing filled with the lesson's own short fields."""
    return template.format(
        failed=lesson.failed, repo=lesson.repo, file=lesson.file, error=lesson.error
    )


def situation_rows(meta: dict[str, list[Lesson]], phrasings: Sequence[str] = ()) -> list[dict]:
    """A pick and a silence row per meta lesson, and one more of each per extra phrasing."""
    pool = [lesson for items in meta.values() for lesson in items]
    rows = []
    for item in build_items(meta, pool, seed=SEED):
        top = narrowed(item, TOP)
        context = context_of(top)
        lesson = item.applies or _lesson_of(item, meta)
        target = item.applies.text() if item.applies else ABSTAIN
        situations = [item.situation, *(phrase(t, lesson) for t in phrasings)]
        rows.extend(chat(context, ASK.format(situation=s), target) for s in situations)
    return rows


def _lesson_of(item, meta: dict[str, list[Lesson]]) -> Lesson:
    lesson_id = item.item_id.rsplit("-", 1)[0]
    return next(
        lesson for items in meta.values() for lesson in items if lesson.lesson_id == lesson_id
    )


def with_unrelated(rows: list[dict], aidev_texts: Sequence[str], seed: int = SEED) -> list[dict]:
    """V3: each situation row's prompt gains UNRELATED AIDev lessons as extra remembered lines."""
    rng = random.Random(seed)
    found = []
    for row in rows:
        system, user, assistant = (m["content"] for m in row["messages"])
        extra = "".join(f"\n- {text}" for text in rng.sample(list(aidev_texts), UNRELATED))
        found.append(chat(system + extra, user, assistant))
    return found


def variant_rows(
    variant: str, split: Split, habit_rows: list[dict], aidev_texts: Sequence[str]
) -> dict:
    """The variant's rows and their counts."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}; known {VARIANTS}")
    questions = [r for r in meta_rows(split.meta) if row_chars(r) <= MAX_ROW_CHARS]
    phrasings = PHRASINGS if variant == "V2" else ()
    situations = situation_rows(split.meta, phrasings)
    if variant == "V3":
        situations = with_unrelated(situations, aidev_texts)
    rows = questions + habit_rows + situations
    random.Random(SEED).shuffle(rows)
    counts = {
        "question_rows": len(questions),
        "habit_rows": len(habit_rows),
        "situation_rows": len(situations),
    }
    return {"rows": rows, "counts": counts}


def main() -> None:
    """Write the variant's train.jsonl and valid.jsonl, and its counts."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True, help="round 2's plan.json")
    parser.add_argument("--habit-split", type=Path, required=True)
    parser.add_argument("--habit-rows", type=Path, required=True)
    parser.add_argument("--aidev-lessons", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidates, _, _ = build_lessons._candidates(args.pool, [])
    habit_repos = [r for r, s in json.loads(args.habit_split.read_text()).items() if s == "train"]
    split = meta_split(distinct(candidates), json.loads(args.plan.read_text()), habit_repos)
    texts = [row["text"] for row in _read_jsonl(args.aidev_lessons) if row["split"] == "train"]
    built = variant_rows(args.variant, split, _read_jsonl(args.habit_rows), texts)
    _jsonl(args.out / "train.jsonl", built["rows"])
    _jsonl(args.out / "valid.jsonl", built["rows"][:8])
    counts = {**built["counts"], "meta_repos": len(split.meta), "variant": args.variant}
    (args.out / "counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
