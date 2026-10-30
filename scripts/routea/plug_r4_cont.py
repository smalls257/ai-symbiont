"""Plug round 4, continuous training (exploratory): nightly situations and Spark labels, then rows.

Usage: uv run python scripts/routea/plug_r4_cont.py prep --work R3 --data D --out O
Usage: uv run python scripts/routea/plug_r4_cont.py label --pairs O/pairs.jsonl --out O/labels.jsonl
Usage:   --run-cap-usd 3
Usage: uv run python scripts/routea/plug_r4_cont.py queries --pairs O/pairs.jsonl --out Q
Usage: uv run python scripts/routea/plug_r4_cont.py rows --work R3 --r4 R4 --spark S --cont O \
Usage:   --pair-scores PS --out C

Why: a nightly judge fed only a repository's few lessons learns caution. Spark labels real nightly
(situation, lesson) pairs from public session text and template lesson text.
"""

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug_judge import JUDGE_SYSTEM, NO, YES, chat  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4 import judge_text, near_miss_rows, nightly_rows  # noqa: E402
from plug_r4_eval import R3_THRESHOLD, accepted, slug  # noqa: E402
from plug_situation import Item, lexical_scores  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

NIGHTS = 10
CANDIDATES_PER_FAILURE = 3
PAIRS_PER_REPO = 60  # the cap that keeps Spark spend under the ledger's run cap
REPLAY_SHARE = 0.25
SEED = 0


@dataclass(frozen=True)
class NightFailure:
    """A failed command with a named error, on a given night."""

    task: str
    night: int
    command: str
    error: str
    file: str

    def exact(self) -> tuple:
        return (self.command, self.error)


@dataclass(frozen=True)
class Stored:
    """A lesson and the task whose session produced it."""

    task: str
    lesson: Lesson


def task_number(task: str) -> int:
    """The pull-request number at the end of `owner__repo-123`, used as the night order."""
    return int(task.rsplit("-", 1)[1])


def night_of(order: list[str]) -> dict[str, int]:
    """Task -> night: one task per night while there are fewer than NIGHTS tasks, else NIGHTS
    contiguous groups of the repository's tasks in order."""
    if len(order) <= NIGHTS:
        return {task: index + 1 for index, task in enumerate(order)}
    return {task: index * NIGHTS // len(order) + 1 for index, task in enumerate(order)}


def sentence(command: str, repo: str, file: str, error: str) -> str:
    """A failure in the round 3 situation wording."""
    return f"Ran `{command}` in {repo} (file {file}). It failed: {error}"


def pair_id(repo: str, situation: str, lesson_id: str) -> str:
    return hashlib.sha1(f"{repo}|{situation}|{lesson_id}".encode()).hexdigest()[:16]


def candidate_pairs(repo: str, failures: list, store: list, taken: set) -> list[dict]:
    """Nightly failures against the lessons stored before their task: the ranker's top few."""
    rows = []
    for failure in failures:
        earlier = [x for x in store if task_number(x.task) < task_number(failure.task)]
        if not earlier or failure.exact() in taken:
            continue
        situation = sentence(failure.command, repo, failure.file, failure.error)
        probe = Item("probe", situation, tuple(x.lesson for x in earlier), None)
        scores = lexical_scores(probe)
        top = sorted(earlier, key=lambda x: (-scores[x.lesson.lesson_id], x.lesson.lesson_id))
        rows.extend(
            {
                "pair_id": pair_id(repo, situation, stored.lesson.lesson_id),
                "repo": repo,
                "night": failure.night,
                "situation": situation,
                "lesson_id": stored.lesson.lesson_id,
                "lesson_text": stored.lesson.text(),
                "idf": round(scores[stored.lesson.lesson_id], 4),
            }
            for stored in top[:CANDIDATES_PER_FAILURE]
        )
    return rows


def label_prompt(situation: str, lesson_text: str) -> str:
    """The teacher's question: one public failure and one template lesson."""
    return (
        f"A coding agent just did this: {situation}\n"
        f"A stored lesson says: {lesson_text}\n"
        "Is this the same failure, so that the lesson's fix would help the agent now? "
        "Reply with only yes or no."
    )


class UnparsableLabelError(ValueError):
    """The teacher's reply was neither yes nor no."""


def parsed_label(reply: str) -> str:
    """`yes` or `no` from a reply; anything else raises (it is counted, never read as no)."""
    words = reply.strip().lower().split()[:1]
    word = words[0].strip(".,!;:") if words else ""
    if word in (YES, NO):
        return word
    raise UnparsableLabelError("reply is neither yes nor no")


def judge_pair_query(pair: dict) -> dict:
    """The judge's query row for one labeled pair."""
    return {
        "question_id": pair["pair_id"],
        "context": JUDGE_SYSTEM,
        "text": judge_text(pair["situation"], pair["lesson_text"]),
    }


def labeled_rows(pairs: list[dict], labels: dict, scores: dict) -> list[dict]:
    """Training rows from the teacher's labels; a pair the round 3 judge got wrong (silent on a
    yes, or speaking on a no) is included twice."""
    rows = []
    for pair in pairs:
        label = labels.get(pair["pair_id"])
        if label is None:
            continue
        row = chat(JUDGE_SYSTEM, judge_text(pair["situation"], pair["lesson_text"]), label)
        spoke = scores[pair["pair_id"]] >= R3_THRESHOLD
        rows += [row, row] if spoke != (label == YES) else [row]
    return rows


def balanced(rows: list[dict], seed: int = SEED) -> list[dict]:
    """Yes and no rows in equal number (the larger side is sampled down, seeded)."""
    yes = [r for r in rows if r["messages"][2]["content"] == YES]
    no = [r for r in rows if r["messages"][2]["content"] == NO]
    size = min(len(yes), len(no))
    rng = random.Random(seed)
    kept = rng.sample(yes, size) + rng.sample(no, size)
    rng.shuffle(kept)
    return kept


def with_replay(
    rows: list[dict], general: list[dict], share: float, seed: int = SEED
) -> list[dict]:
    """The rows plus round 3 general rows making up `share` of the total."""
    needed = round(len(rows) * share / (1 - share))
    rng = random.Random(seed)
    mixed = rows + rng.sample(general, min(needed, len(general)))
    rng.shuffle(mixed)
    return mixed


def repo_rows(
    picks: list, invented: dict, misses: list, labeled: list, general: list
) -> list[dict]:
    """One repository's training rows: invented situations, labeled pairs, near-misses, replay."""
    base = nightly_rows(picks, invented, misses)
    return with_replay(balanced(base + labeled), general, REPLAY_SHARE)


def near_misses(work: Path) -> list[dict]:
    """Near-miss rows from round 3's validation mistakes only."""
    from plug_judge_cli import seed_mean_scores  # noqa: PLC0415

    items, _ = load_items(work, "validation")
    paths = [work / "scores" / f"validation-judge-s{s}.jsonl" for s in range(3)]
    return near_miss_rows(items, seed_mean_scores(paths), R3_THRESHOLD)


def write_repo(args: argparse.Namespace, repo: str, rows: list[dict], queries: list[dict]) -> None:
    """One repository's train and valid rows and its eval queries."""
    folder = args.out / "habits10" / slug(repo)
    _jsonl(folder / "train.jsonl", rows)
    _jsonl(folder / "valid.jsonl", rows[:8])
    _jsonl(args.out / "queries" / f"{slug(repo)}.jsonl", queries)


def write_rows(args: argparse.Namespace) -> dict:
    """Per repository: train and valid rows, and its eval queries."""
    items, repo_of = load_items(args.work, "scored")
    invented = accepted(args.spark / "invent-val40.jsonl", "situations")
    misses = near_misses(args.work)
    pairs = _read_jsonl(args.cont / "pairs.jsonl")
    read = _read_jsonl(args.cont / "labels.jsonl")
    labels = {r["pair_id"]: r["label"] for r in read if "label" in r}
    scores = {r["question_id"]: r["p_yes"] for r in _read_jsonl(args.pair_scores)}
    general = _read_jsonl(args.work / "rows" / "train.jsonl")
    queries = _read_jsonl(args.work / "scored-queries.jsonl")
    sizes = {}
    for repo in sorted(set(repo_of.values())):
        picks = [i for i in items if repo_of[i.item_id] == repo and i.applies is not None]
        labeled = labeled_rows([p for p in pairs if p["repo"] == repo], labels, scores)
        rows = repo_rows(picks, invented, misses, labeled, general)
        mine = [q for q in queries if repo_of[q["question_id"].split("::")[0]] == repo]
        write_repo(args, repo, rows, mine)
        sizes[slug(repo)] = len(rows)
    return {"repos": len(sizes), "rows_total": sum(sizes.values()), "labeled_pairs": len(labels)}


def add_habits(bundle: Path, habits: list[dict], share: float) -> int:
    """Habit-replay rows added to every repository's training rows so they make up `share` of
    them (sampled with replacement, seeded); returns the repositories changed."""
    from plug_r4_eval import with_habits  # noqa: PLC0415

    folders = sorted((bundle / "habits10").glob("*/train.jsonl"))
    for path in folders:
        rows = with_habits(_read_jsonl(path), habits, share)
        _jsonl(path, rows)
        _jsonl(path.with_name("valid.jsonl"), rows[:8])
    return len(folders)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("prep", "label", "queries", "rows"))
    for flag in (
        "--work",
        "--data",
        "--out",
        "--pairs",
        "--labels",
        "--r4",
        "--spark",
        "--cont",
        "--pair-scores",
    ):
        parser.add_argument(flag, type=Path)
    parser.add_argument("--run-cap-usd", type=float)
    args = parser.parse_args()
    from plug_r4_cont_io import run_label, run_prep, run_queries  # noqa: PLC0415

    if args.stage == "prep":
        print(json.dumps(run_prep(args)))
    elif args.stage == "label":
        print(json.dumps(run_label(args)))
    elif args.stage == "queries":
        print(json.dumps(run_queries(args)))
    else:
        print(json.dumps(write_rows(args)))


if __name__ == "__main__":
    main()
