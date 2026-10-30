"""Plug round 4 continuous training, the parts that read sessions, call Spark or write queries.

Why: `plug_r4_cont.py` stays pure; this file holds the three stages that touch the exports, the
Spark door or the GPU's query files, so the pure rows can be tested without them.
"""

import json
from collections import Counter
from pathlib import Path

from lessons import lessons_in_session
from plug_r3_run import load_items
from plug_r4_cont import (
    PAIRS_PER_REPO,
    SEED,
    NightFailure,
    Stored,
    UnparsableLabelError,
    candidate_pairs,
    judge_pair_query,
    label_prompt,
    night_of,
    parsed_label,
    task_number,
)
from plug_r4_eval import slug
from plug_r4_primary import session_failures
from plug_r4_spark import RETRIES, WORKERS, asked, session
from warm_start import _jsonl, _read_jsonl


def repo_nights(path: Path, eval_ids: set[str], taken: set) -> tuple[list, list]:
    """A repository's nightly failures (not eval lessons) and its stored eval lessons."""
    import build_lessons  # noqa: PLC0415  (reads the exports)

    sessions = build_lessons._sessions_in(path)
    tasks = sorted({s[0].task_id for s in sessions}, key=task_number)
    nights = night_of(tasks)
    failures, stored = {}, []
    for one in sessions:
        task = one[0].task_id
        stored += [
            Stored(task, x) for x in lessons_in_session(one, Counter()) if x.lesson_id in eval_ids
        ]
        for f in session_failures(one):
            if f.exact() not in taken:
                failures[(task, f.exact())] = NightFailure(
                    task, nights[task], f.command, f.error, f.file
                )
    return list(failures.values()), stored


def run_prep(args) -> dict:
    """Candidate (situation, lesson) pairs per repository, capped, written for labeling."""
    import random  # noqa: PLC0415

    items, repo_of = load_items(args.work, "scored")
    lessons: dict[str, list] = {}
    for item in items:
        if item.applies is not None:
            lessons.setdefault(repo_of[item.item_id], []).append(item.applies)
    pairs = []
    for repo, own in sorted(lessons.items()):
        taken = {(x.failed, x.error) for x in own}
        failures, stored = repo_nights(
            args.data / f"{slug(repo)}.jsonl", {x.lesson_id for x in own}, taken
        )
        found = candidate_pairs(repo, failures, stored, taken)
        random.Random(f"{SEED}:{repo}").shuffle(found)
        pairs += found[:PAIRS_PER_REPO]
    _jsonl(args.out / "pairs.jsonl", pairs)
    return {"pairs": len(pairs), "repos_with_pairs": len({p["repo"] for p in pairs})}


def label_one(spark, pair: dict) -> dict:
    """The teacher's label for one pair, or the reason it could not be read."""
    reply = asked(spark, label_prompt(pair["situation"], pair["lesson_text"]), "label")
    try:
        return {"pair_id": pair["pair_id"], "label": parsed_label(reply.text)}
    except UnparsableLabelError as error:
        return {"pair_id": pair["pair_id"], "rejected": str(error)}


def run_label(args) -> dict:
    """Label every pair not yet in the output, appending as results land (a rerun resumes)."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    spark = session(args.run_cap_usd)
    pairs = _read_jsonl(args.pairs)
    done = {r["pair_id"] for r in _read_jsonl(args.out)} if args.out.exists() else set()
    todo = [p for p in pairs if p["pair_id"] not in done]
    with ThreadPoolExecutor(WORKERS) as pool, args.out.open("a") as sink:
        for result in pool.map(lambda pair: label_one(spark, pair), todo):
            sink.write(json.dumps(result) + "\n")
            sink.flush()
    rows = _read_jsonl(args.out)
    kinds = Counter(r.get("label", "rejected") for r in rows)
    return {"pairs": len(pairs), "labeled": dict(kinds), **RETRIES}


def run_queries(args) -> dict:
    """The judge's query rows for every pair, for GPU scoring."""
    pairs = _read_jsonl(args.pairs)
    _jsonl(args.out, [judge_pair_query(p) for p in pairs])
    return {"queries": len(pairs)}
