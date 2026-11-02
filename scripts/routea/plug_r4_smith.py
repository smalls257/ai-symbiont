"""Code-fix lessons study on SWE-smith: events, the history/scored split, counts and items.

Usage: uv run python scripts/routea/plug_r4_smith.py counts --raw DIR --exclude X... --out F
Usage: uv run python scripts/routea/plug_r4_smith.py build --raw DIR --repos R.json --out DIR

SWE-smith tasks have no creation dates (the bugs are synthetic and injected, the agent's
mistakes are real), so tasks are ordered by a seeded hash: the first half is the "history" the
nightly adapters may learn from, the second half is scored against that fixed store.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import (  # noqa: E402
    ERROR_CLASS,
    MAX_COMMAND_CHARS,
    Lesson,
    error_line,
    repo_name,
    shown_command,
)
from plug_judge import judge_queries  # noqa: E402
from plug_r4_cont import pair_id, sentence  # noqa: E402
from plug_r4_primary import (  # noqa: E402
    SHORTLIST,
    TaskEvents,
    case_item,
    chosen_negatives,
    merged_store,
    session_failures,
    task_cases,
)
from plug_situation import Item, item_record, lexical_scores  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

from symbiont.miner.commands import normalise_command  # noqa: E402
from symbiont.readers.openhands import PROVENANCE  # noqa: E402
from symbiont.records.schema import Kind, Record  # noqa: E402

SEED = 0
TARGET_POSITIVES = 450  # 80% power for the exact bound under 5% at 2.99% wrong (see the prereg)
MAX_REPOS = 4


def hashed_order(tasks: list[str]) -> list[str]:
    """Tasks in a seeded-hash order (the stand-in for creation time)."""
    return sorted(tasks, key=lambda task: hashlib.sha1(f"{SEED}:{task}".encode()).hexdigest())


def records_of(row: dict, repo: str) -> list[Record]:
    """One trajectory's code-running commands as records; exit code 1 when the output names an
    error (SWE-smith observations carry no exit code)."""
    return [
        Record(
            harness="swe-smith",
            project=repo,
            session_id=row["traj_id"],
            step=index,
            kind=Kind.COMMAND,
            raw=step["output"],
            provenance=PROVENANCE,
            command=step["command"],
            exit_code=1 if error_line(step["output"]) else 0,
            task_id=row["instance_id"],
        )
        for index, step in enumerate(row["steps"])
        if step["kind"] == "run"
    ]


def passes(step: dict) -> bool:
    """A run whose output names no error."""
    return step["kind"] == "run" and not error_line(step["output"])


def fix_for(steps: list[dict], index: int) -> list[str] | None:
    """The paths edited between a failed run and the next run of the same command that passed,
    or None if there was no such edited-then-passed rerun."""
    failed = shown_command(steps[index]["command"])
    edited: list[str] = []
    for step in steps[index + 1 :]:
        if step["kind"] == "edit":
            edited.append(step["path"])
        elif step["kind"] == "run" and shown_command(step["command"]) == failed:
            return list(dict.fromkeys(edited)) if edited and passes(step) else None
    return None


def code_fix_lessons(row: dict, repo: str) -> list[Lesson]:
    """Lessons of one trajectory: a command failed (an error line), code was edited, the same
    command reran and passed. The lesson names the failure and the edited files."""
    found = []
    for index, step in enumerate(row["steps"]):
        error = error_line(step["output"]) if step["kind"] == "run" else None
        paths = fix_for(row["steps"], index) if error else None
        failed = shown_command(step["command"]) if error else ""
        if not paths or len(failed) > MAX_COMMAND_CHARS or "\n" in failed:
            continue
        program, target = normalise_command(failed)
        lesson_id = hashlib.sha1(f"{row['traj_id']}:{index}".encode()).hexdigest()[:12]
        fix = "edit " + ", ".join(paths[:2])
        found.append(
            Lesson(
                lesson_id,
                repo_name(repo),
                program,
                target,
                failed,
                error,
                error_class_of(error),
                fix,
                tuple(paths[:2]),
            )
        )
    return found


def error_class_of(error: str) -> str:
    """The exception class named in an error line (error_line guarantees one)."""
    return ERROR_CLASS.search(error).group(1)


def repo_events(path: Path) -> list[TaskEvents]:
    """A repository's tasks with the failures and code-fix lessons of all their trajectories."""
    failures, lessons = defaultdict(list), defaultdict(list)
    for row in _read_jsonl(path):
        failures[row["instance_id"]] += session_failures(records_of(row, path.stem))
        lessons[row["instance_id"]] += code_fix_lessons(row, path.stem)
    return [TaskEvents(task, "", tuple(failures[task]), tuple(lessons[task])) for task in failures]


def split_tasks(events: list[TaskEvents]) -> tuple[list[TaskEvents], list[TaskEvents]]:
    """History (first half of the hashed order) and scored tasks (second half)."""
    order = hashed_order([e.task for e in events])
    cut = len(order) // 2
    history = set(order[:cut])
    return [e for e in events if e.task in history], [e for e in events if e.task not in history]


def scored_cases(repo: str, events: list[TaskEvents]) -> tuple[list, tuple]:
    """Cases of the scored half against the fixed history store, and that store."""
    history, scored = split_tasks(events)
    store = merged_store(x for e in history for x in e.lessons)
    return [c for e in scored for c in task_cases(repo, e, store)] if store else [], store


def counts(args: argparse.Namespace) -> dict:
    """Per candidate repository: tasks, history lessons, scored positives, negative candidates."""
    excluded: set[str] = set()
    for path in args.exclude:
        excluded |= set(json.loads(path.read_text()))
    found = {}
    for path in sorted(args.raw.glob("*.jsonl")):
        if path.stem in excluded:
            continue
        events = repo_events(path)
        cases, store = scored_cases(path.stem, events)
        found[path.stem] = {
            "tasks": len(events),
            "history_lessons": len(store),
            "positives": sum(1 for case in cases if case.matches),
            "negative_candidates": sum(1 for case in cases if not case.matches),
        }
    return found


def choose_repos(found: dict) -> list[str]:
    """The pre-declared rule: repos by trajectory-rich order of positives, the smallest set of
    at least two reaching TARGET_POSITIVES, at most MAX_REPOS."""
    ranked = sorted(found, key=lambda name: -found[name]["positives"])
    chosen, total = [], 0
    for repo in ranked[:MAX_REPOS]:
        chosen.append(repo)
        total += min(found[repo]["positives"], found[repo]["negative_candidates"])
        if len(chosen) >= 2 and total >= TARGET_POSITIVES:
            break
    return chosen


def write_items(out: Path, items: list, use: list) -> dict:
    """The item files, the negative-id list and a manifest with every hash."""
    records = [
        item_record(item) | {"repo": case.repo, "task": case.failure.task}
        for item, case in zip(items, use, strict=True)
    ]
    out.mkdir(parents=True, exist_ok=True)
    _jsonl(out / "primary-items.jsonl", records)
    _jsonl(out / "primary-queries.jsonl", judge_queries(items, SHORTLIST))
    quiet = sorted(item.item_id for item in items if item.applies is None)
    (out / "primary-negatives.txt").write_text("\n".join(quiet) + "\n")
    kinds = Counter("pick" if item.applies else "silence" for item in items)
    names = ("primary-items.jsonl", "primary-queries.jsonl", "primary-negatives.txt")
    hashes = {n: hashlib.sha256((out / n).read_bytes()).hexdigest() for n in names}
    manifest = {"items": len(items), "kinds": dict(kinds), "sha256": hashes}
    (out / "primary-manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def build(args: argparse.Namespace) -> dict:
    """Items and judge queries for the chosen repos (positives plus 1:1 negatives)."""
    chosen = json.loads(args.repos.read_text())
    by_repo = {repo_name(stem): repo_events(args.raw / f"{stem}.jsonl") for stem in chosen}
    pool = merged_store(x for events in by_repo.values() for e in events for x in e.lessons)
    cases = [case for name, events in by_repo.items() for case in scored_cases(name, events)[0]]
    use = [case for case in cases if case.matches] + chosen_negatives(cases)
    items = [case_item(case, pool) for case in use]
    return {"repos": sorted(by_repo), **write_items(args.out, items, use)}


LESSONS_PER_REPO = 150  # lessons the nightly adapter learns per repository (seeded, history only)
PAIRS_PER_REPO = 60


def history_store(events: list[TaskEvents]) -> list[Lesson]:
    """The history half's lessons, capped to LESSONS_PER_REPO by a seeded hash of the lesson id."""
    history, _ = split_tasks(events)
    store = merged_store(x for e in history for x in e.lessons)
    ranked = sorted(store, key=lambda x: hashlib.sha1(f"{SEED}:{x.lesson_id}".encode()).hexdigest())
    return ranked[:LESSONS_PER_REPO]


def history_pairs(repo: str, events: list[TaskEvents], store: list[Lesson]) -> list[dict]:
    """History failures against the capped store's top few lessons by ranker score, for Spark to
    label; a failure is never paired with a lesson mined from its own task."""
    history, _ = split_tasks(events)
    own = {x.lesson_id: e.task for e in history for x in e.lessons}
    pairs = []
    for failure in {(f.task, f.exact()): f for e in history for f in e.failures}.values():
        others = [x for x in store if own.get(x.lesson_id) != failure.task]
        if not others:
            continue
        situation = sentence(failure.command, repo, failure.file, failure.error)
        scores = lexical_scores(Item("probe", situation, tuple(others), None))
        top = sorted(others, key=lambda x: (-scores[x.lesson_id], x.lesson_id))[:3]
        pairs += [
            {
                "pair_id": pair_id(repo, situation, x.lesson_id),
                "repo": repo,
                "night": 0,
                "situation": situation,
                "lesson_id": x.lesson_id,
                "lesson_text": x.text(),
                "idf": round(scores[x.lesson_id], 4),
            }
            for x in top
        ]
    return sorted(
        pairs, key=lambda pair: hashlib.sha1(f"{SEED}:{pair['pair_id']}".encode()).hexdigest()
    )


def prep(args: argparse.Namespace) -> dict:
    """The nightly arm's inputs: the capped history lessons and the pairs Spark will label."""
    lessons, pairs = [], []
    for stem in json.loads(args.repos.read_text()):
        repo = repo_name(stem)
        events = repo_events(args.raw / f"{stem}.jsonl")
        store = history_store(events)
        lessons += [asdict(x) for x in store]
        pairs += history_pairs(repo, events, store)[:PAIRS_PER_REPO]
    args.out.mkdir(parents=True, exist_ok=True)
    _jsonl(args.out / "lessons.jsonl", lessons)
    _jsonl(args.out / "pairs.jsonl", pairs)
    return {"lessons": len(lessons), "pairs": len(pairs)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("counts", "build", "prep"))
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    parser.add_argument("--repos", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "counts":
        found = counts(args)
        document = {"per_repo": found, "chosen": choose_repos(found)}
        args.out.write_text(json.dumps(document, indent=1) + "\n")
        print(json.dumps(document)[:1500])
    elif args.stage == "build":
        print(json.dumps(build(args)))
    else:
        print(json.dumps(prep(args)))


if __name__ == "__main__":
    main()
