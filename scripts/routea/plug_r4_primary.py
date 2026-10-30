"""Plug round 4's primary items: real later recurrences, plus negatives, built from the exports.

Usage: uv run python scripts/routea/plug_r4_primary.py build --pool P... --dates D... \
Usage:   --fresh-pool F --recur-counts C --rest-counts R --out DIR

Why: the primary claim is about a repository's own failure coming back in a later, different task,
so each positive item is a later failure whose exact key an earlier task's lesson has, with the
store as it stood before that task; each negative is a later failure no earlier lesson matches
(right answer: silence). Items are written for scoring; the build refuses any count other than the
pre-declared 251 recurrences in 89 repositories (a smaller set is a different run, not a fallback).
"""

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson, error_line, lessons_in_session, shown_command  # noqa: E402
from plug_judge import judge_queries  # noqa: E402
from plug_situation import PROMPT_LESSONS, Item, item_record, key_of, situation_of  # noqa: E402
from warm_start import _jsonl  # noqa: E402

from symbiont.miner.commands import normalise_command  # noqa: E402
from symbiont.records.schema import Kind, Record  # noqa: E402

PRIMARY_POSITIVES, PRIMARY_REPOS = 251, 89  # the committed counts (rule 2e244dc, be77a22)
SHORTLIST = 10
SEED = 0


class PrimaryCountError(ValueError):
    """The built primary set is not the pre-declared 251 recurrences in 89 repositories."""


@dataclass(frozen=True)
class Failure:
    """A failed command with a named error, as a later situation."""

    task: str
    command: str
    error: str
    file: str

    def exact(self) -> tuple:
        return (self.command, self.error)

    def loose(self) -> tuple:
        return (normalise_command(self.command), self.error)


@dataclass(frozen=True)
class TaskEvents:
    """One task: its failures and the lessons its sessions yielded."""

    task: str
    date: str
    failures: tuple[Failure, ...]
    lessons: tuple[Lesson, ...]


@dataclass(frozen=True)
class Case:
    """A later failure, the store before its task, and whether an earlier lesson matches it."""

    repo: str
    failure: Failure
    store: tuple[Lesson, ...]
    matches: tuple[Lesson, ...]


def session_failures(session: Sequence[Record]) -> list[Failure]:
    """The session's failed commands that name an error."""
    found = []
    for record in session:
        if record.kind == Kind.COMMAND and record.exit_code and record.command:
            error = error_line(record.raw)
            if error:
                shown = shown_command(record.command)
                found.append(Failure(record.task_id, shown, error, normalise_command(shown)[1]))
    return found


def exact_of(lesson: Lesson) -> tuple:
    return (lesson.failed, lesson.error)


def loose_of(lesson: Lesson) -> tuple:
    return (normalise_command(lesson.failed), lesson.error)


def merged_store(lessons: Iterable[Lesson]) -> tuple[Lesson, ...]:
    """Lessons with identical (command, error, fix) merged to one, in lesson-id order."""
    by_key = {}
    for lesson in sorted(lessons, key=lambda x: x.lesson_id):
        by_key.setdefault((lesson.failed, lesson.error, lesson.fix), lesson)
    return tuple(by_key.values())


def task_cases(repo: str, events: TaskEvents, store: tuple[Lesson, ...]) -> list[Case]:
    """One task's distinct failures against the store: matched (positive) or unmatched (negative);
    a loose-only match is neither."""
    cases = []
    for failure in {item.exact(): item for item in events.failures}.values():
        exact = tuple(x for x in store if exact_of(x) == failure.exact())
        loose = any(loose_of(x) == failure.loose() for x in store)
        if exact or not loose:
            cases.append(Case(repo, failure, store, exact))
    return cases


def repo_cases(repo: str, tasks: Sequence[TaskEvents]) -> list[Case]:
    """Each later task's cases against the lessons of the tasks before it (by date, ties by task
    id). The first task has no store and gives no case."""
    earlier: list[Lesson] = []
    cases = []
    for events in sorted(tasks, key=lambda task: (task.date, task.task)):
        if earlier:
            cases += task_cases(repo, events, merged_store(earlier))
        earlier += events.lessons
    return cases


def case_id(case: Case) -> str:
    """A stable id from repository, task and exact key."""
    digest = hashlib.sha1(repr((case.failure.task, case.failure.exact())).encode()).hexdigest()
    return f"{case.repo.replace('/', '__')}:{case.failure.task}:{digest[:8]}"


def chosen_negatives(cases: Sequence[Case], seed: int = SEED) -> list[Case]:
    """Per repository as many negatives as it has positives, ordered by a seeded hash of the id."""
    chosen = []
    for repo in sorted({c.repo for c in cases}):
        own = [case for case in cases if case.repo == repo]
        positives = sum(1 for case in own if case.matches)
        quiet = sorted(
            (case for case in own if not case.matches),
            key=lambda case: hashlib.sha1(f"{seed}:{case_id(case)}".encode()).hexdigest(),
        )
        chosen += quiet[:positives]
    return chosen


def pseudo_lesson(case: Case) -> Lesson:
    """The failure as a lesson-shaped record, only to reuse the round 3 situation wording."""
    seen = case.failure
    return Lesson("situation", case.repo, "", seen.file, seen.command, seen.error, "", "", ())


def capped_store(case: Case, applies: Lesson | None, rng: random.Random) -> list[Lesson]:
    """The store, cut to the prompt size by a seeded sample that always keeps the applicable one."""
    store = list(case.store)
    if len(store) <= PROMPT_LESSONS - 1:
        return store
    rest = [x for x in store if x is not applies]
    keep = [] if applies is None else [applies]
    return keep + rng.sample(rest, PROMPT_LESSONS - 1 - len(keep))


def case_item(case: Case, pool: Sequence[Lesson]) -> Item:
    """The item: store plus seeded distractors from other repositories up to the prompt size."""
    rng = random.Random(f"{SEED}:{case_id(case)}")
    applies = case.matches[0] if case.matches else None
    store = capped_store(case, applies, rng)
    banned = {key_of(x) for x in case.matches}
    others = [x for x in pool if x.repo != case.repo and key_of(x) not in banned]
    needed = PROMPT_LESSONS - len(store)
    if len(others) < needed:
        raise ValueError(f"cannot fill {PROMPT_LESSONS} lessons for {case_id(case)}")
    shown = [*store, *rng.sample(others, needed)]
    rng.shuffle(shown)
    suffix = "pick" if applies else "silence"
    situation = situation_of(pseudo_lesson(case))
    return Item(f"{case_id(case)}-{suffix}", situation, tuple(shown), applies)


def build_items(by_repo: dict[str, Sequence[TaskEvents]]) -> tuple[list[Item], dict[str, str]]:
    """Positive items for every recurrence, negative items as chosen; each item's repository."""
    cases = [c for repo, tasks in sorted(by_repo.items()) for c in repo_cases(repo, tasks)]
    pool = merged_store(x for tasks in by_repo.values() for t in tasks for x in t.lessons)
    use = [c for c in cases if c.matches] + chosen_negatives(cases)
    items = [case_item(case, pool) for case in use]
    return items, {item.item_id: case.repo for item, case in zip(items, use, strict=True)}


def counts_of(items: Sequence[Item], repo_of: dict[str, str]) -> dict:
    """The counts the refusal and the prereg pin."""
    positives = [i for i in items if i.applies is not None]
    return {
        "positives": len(positives),
        "positive_repos": len({repo_of[i.item_id] for i in positives}),
        "negatives": len(items) - len(positives),
        "single_fix_positives": sum(
            1
            for i in positives
            if sum(exact_of(x) == exact_of(i.applies) for x in i.prompt_lessons) == 1
        ),
    }


def checked_counts(items: Sequence[Item], repo_of: dict[str, str]) -> dict:
    """The counts, or PrimaryCountError if positives or repositories differ from the declaration."""
    found = counts_of(items, repo_of)
    if (found["positives"], found["positive_repos"]) != (PRIMARY_POSITIVES, PRIMARY_REPOS):
        raise PrimaryCountError(
            f"built {found['positives']} recurrences in {found['positive_repos']} repos, "
            f"declared {PRIMARY_POSITIVES} in {PRIMARY_REPOS}"
        )
    return found


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_primary(out: Path, items: list[Item], repo_of: dict[str, str]) -> dict:
    """Items, judge queries, the negative-id list and a manifest with every hash."""
    found = checked_counts(items, repo_of)
    records = [item_record(i) | {"repo": repo_of[i.item_id]} for i in items]
    _jsonl(out / "primary-items.jsonl", records)
    _jsonl(out / "primary-queries.jsonl", judge_queries(items, SHORTLIST))
    quiet = sorted(i.item_id for i in items if i.applies is None)
    (out / "primary-negatives.txt").write_text("\n".join(quiet) + "\n")
    manifest = {
        **found,
        "kinds": dict(Counter("pick" if i.applies else "silence" for i in items)),
        "sha256": {
            name: sha256_of(out / name)
            for name in ("primary-items.jsonl", "primary-queries.jsonl", "primary-negatives.txt")
        },
    }
    (out / "primary-manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def primary_repos(fresh: dict, recur: dict, rest: dict) -> set[str]:
    """Never-read and meta2-only repositories with an exact recurrence, plus the rest list's."""
    counted = recur["nebius"]["exact"]["per_repo"]
    in_fresh = {entry["repo"] for entry in fresh["repos"]}
    return {repo for repo in counted if repo in in_fresh} | set(rest["nebius"]["exact"]["per_repo"])


def load_events(pools: Sequence[Path], repos: set[str], dates: dict[str, str]) -> dict:
    """repo -> TaskEvents from the exports (each session id once); a task without a date raises."""
    from build_lessons import _sessions  # noqa: PLC0415  (reads the exports)
    from plug_r4_recur import repo_of as repo_of_session  # noqa: PLC0415

    seen: set[str] = set()
    grouped: dict[str, dict[str, list]] = {}
    for pool in pools:
        for session in _sessions(pool, []):
            repo, sid = repo_of_session(session), session[0].session_id
            if repo not in repos or sid in seen:
                continue
            seen.add(sid)
            task = session[0].task_id
            if task not in dates:
                raise KeyError(f"no creation date for task {task}")
            slot = grouped.setdefault(repo, {}).setdefault(task, [[], []])
            slot[0] += session_failures(session)
            slot[1] += lessons_in_session(session, Counter())
    return {
        repo: [TaskEvents(t, dates[t], tuple(f), tuple(x)) for t, (f, x) in tasks.items()]
        for repo, tasks in grouped.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("build",))
    parser.add_argument("--pool", type=Path, nargs="+", required=True)
    parser.add_argument("--dates", type=Path, nargs="+", required=True)
    parser.add_argument("--fresh-pool", type=Path, required=True)
    parser.add_argument("--recur-counts", type=Path, required=True)
    parser.add_argument("--rest-counts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    dates: dict[str, str] = {}
    for path in args.dates:
        dates |= json.loads(path.read_text())
    repos = primary_repos(
        json.loads(args.fresh_pool.read_text()),
        json.loads(args.recur_counts.read_text()),
        json.loads(args.rest_counts.read_text()),
    )
    items, repo_of = build_items(load_events(args.pool, repos, dates))
    print(json.dumps(write_primary(args.out, items, repo_of)))


if __name__ == "__main__":
    main()
