"""Plug (L2L-A2): the scored split, the unseen checks, and the confabulation and habit scorers.

Usage: uv run python scripts/routea/plug.py plan --pool P --habit-split S --habit-rows H --work W
Usage: uv run python scripts/routea/plug.py check --pool P --habit-rows H --habit-questions Q
Usage:   --habit-system Y --prereg prereg/2026-10-28-l2l-a2.md --work W

The plan raises before any answer if meta-training and the scored repos share a repo name or a
lesson id: a reader scored on repos it trained on would report in-sample recall as plug-and-play.
Shared (error class, fix tokens) keys across repos are legitimate recurrences and are counted.
Pure scoring; only the plan stage reads the pool.
"""

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from l2l_quick import MAX_ROW_CHARS, meta_rows, row_chars  # noqa: E402
from lessons import Lesson  # noqa: E402
from scoring import _QUOTES  # noqa: E402
from warm_start import BLOCKED, MIN_LESSONS, _jsonl  # noqa: E402

from symbiont.eval.prereg_git import run_provenance  # noqa: E402

FEASIBILITY_REPOS = frozenset({"Azure/msrest-for-python", "CORE-GATECH-GROUP/serpent-tools"})
MIN_META_LESSONS = 2  # a meta-train prompt needs a lesson to read and one beside it
ABSTAIN_PREFIX = "No lesson I hold covers that"
PREREG_NAME = "2026-10-28-l2l-a2.md"  # the name the draft takes at its freeze
# Input hashes pinned in the prereg (Data and split, Metrics 4); a scored run refuses other inputs.
PINNED = {
    "pool_index_sha256": "a14f22f0158a2ac568f84ffdbbbafaa01059cf22abebc5f4370679623cd258ff",
    "habit_rows_sha256": "fa863cb3f13bf66907a16d076cf4d2ffab705272ef785d16ea93c19a271c06ea",
    "habit_questions_sha256": "78d2267d767202737d21b215bcfaa74ad0413a2a0c72f20d968843a8b22c3b1f",
    "habit_system_sha256": "c4678461a047be012a1ea9287c7ac66f73aa26cad8dd0c87c2f1469d603ed2e8",
}


class InputHashMismatchError(ValueError):
    """An input of the scored run differs from the hash its prereg pins; names the input."""


class SharedSplitError(ValueError):
    """Meta-training and the scored repos share a repo or a lesson; names what is shared."""


@dataclass(frozen=True)
class Split:
    """The scored repos, the meta-train repos and the control pairing, by name."""

    test: dict[str, list[Lesson]]
    meta: dict[str, list[Lesson]]
    control_of: dict[str, str]  # scored repo -> repo whose lessons are its wrong lessons


def fold(text: str) -> str:
    """Quotes stripped and whitespace folded, exactly as `scoring.recalled` compares text."""
    return " ".join(_QUOTES.sub(" ", text).split())


def lesson_key(lesson: Lesson) -> tuple[str, tuple[str, ...]]:
    """What makes two lessons the same failure."""
    return lesson.error_class, lesson.added


def distinct(candidates: Iterable[Lesson]) -> dict[str, list[Lesson]]:
    """Each repo's distinct failures in lesson-id order, blocked repos left out."""
    seen: set[tuple[str, tuple[str, tuple[str, ...]]]] = set()
    found: dict[str, list[Lesson]] = {}
    for lesson in sorted(candidates, key=lambda item: item.lesson_id):
        if lesson.repo in BLOCKED or (lesson.repo, lesson_key(lesson)) in seen:
            continue
        seen.add((lesson.repo, lesson_key(lesson)))
        found.setdefault(lesson.repo, []).append(lesson)
    return found


def plan_split(by_repo: dict[str, list[Lesson]], habit_repos: Iterable[str]) -> Split:
    """Scored repos (10 or more lessons, not feasibility), meta-train repos (the rest), pairing."""
    test = {
        repo: items
        for repo, items in sorted(by_repo.items())
        if len(items) >= MIN_LESSONS and repo not in FEASIBILITY_REPOS
    }
    meta = {
        repo: items
        for repo, items in sorted(by_repo.items())
        if repo not in test and repo not in FEASIBILITY_REPOS and len(items) >= MIN_META_LESSONS
    }
    names = sorted(test)
    control_of = {repo: names[(i + 1) % len(names)] for i, repo in enumerate(names)}
    split = Split(test, meta, control_of)
    check_unseen(split, habit_repos)
    return split


def check_unseen(split: Split, habit_repos: Iterable[str]) -> None:
    """Raise SharedSplitError on a repo or lesson id held by both sides."""
    habits = set(habit_repos)
    for left, right, label in (
        (set(split.meta), set(split.test), "meta-train and scored"),
        (habits, set(split.test), "habit rows and scored"),
        (habits, set(split.meta), "habit rows and meta-train"),
    ):
        if left & right:
            raise SharedSplitError(f"{label} share repos: {sorted(left & right)}")
    meta_ids = {item.lesson_id for items in split.meta.values() for item in items}
    test_ids = {item.lesson_id for items in split.test.values() for item in items}
    if meta_ids & test_ids:
        raise SharedSplitError(
            f"meta-train and scored share lesson ids: {sorted(meta_ids & test_ids)}"
        )


def shared_keys(split: Split) -> list[str]:
    """Scored lesson ids whose failure key also occurs in meta-training (sensitivity set)."""
    meta_keys = {lesson_key(item) for items in split.meta.values() for item in items}
    return sorted(
        item.lesson_id
        for items in split.test.values()
        for item in items
        if lesson_key(item) in meta_keys
    )


def confabulates(answer: str, own: Sequence[Lesson], wrong: Sequence[Lesson]) -> bool:
    """True if the answer asserts a wrong-repo lesson's fix that no own lesson shares."""
    flat = fold(answer)
    own_keys = {lesson_key(item) for item in own}
    for lesson in wrong:
        if not lesson.added:
            raise ValueError(f"lesson {lesson.lesson_id} has no fix tokens to compare")
        if lesson_key(lesson) in own_keys:
            continue
        tokens = all(fold(token) in flat for token in lesson.added)
        if tokens or fold(lesson.fix) in flat:
            return True
    return False


def abstains(answer: str) -> bool:
    """The answer says no lesson covers the question (a2's trained string or its gist)."""
    folded = " ".join(answer.split())
    return folded.startswith(ABSTAIN_PREFIX) or "no lesson" in folded.lower()


def ranked_hit(own_kind: str, scores: dict[str, float]) -> bool:
    """A habit hit: the question's own kind has the strictly highest mean log-likelihood."""
    best = max(scores.values())
    leaders = [kind for kind, value in scores.items() if value == best]
    return leaders == [own_kind]


def sha256_of(path: Path) -> str:
    """The file's sha256, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def pool_index_sha(pool: Path) -> str:
    """One hash over every pool file's name and content hash, in name order."""
    lines = (f"{path.name} {sha256_of(path)}" for path in sorted(pool.glob("*.jsonl")))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def verify_inputs(found: dict[str, str], pinned: dict[str, str] = PINNED) -> None:
    """Raise InputHashMismatchError unless every pinned input hash is present and equal."""
    for name, expected in pinned.items():
        if found.get(name) != expected:
            raise InputHashMismatchError(f"{name} is {found.get(name)}, the prereg pins {expected}")


def input_hashes(pool: Path, habit_rows: Path, habit_questions: Path, habit_system: Path) -> dict:
    """The hashes `verify_inputs` compares, computed from the files a run is about to read."""
    return {
        "pool_index_sha256": pool_index_sha(pool),
        "habit_rows_sha256": sha256_of(habit_rows),
        "habit_questions_sha256": sha256_of(habit_questions),
        "habit_system_sha256": sha256_of(habit_system),
    }


def scored_run_label(prereg: str) -> dict:
    """run_provenance of a scored Plug run; raises unless the prereg is frozen as PREREG_NAME."""
    return run_provenance(scored=True, prereg=prereg, expects=PREREG_NAME)


def meta_train_rows(split: Split, habit_rows: list[dict]) -> tuple[list[dict], int]:
    """The a2 meta-train rows (recipe of `l2l_quick.write_meta`) and how many were too long."""
    built = meta_rows(split.meta)
    kept = [row for row in built if row_chars(row) <= MAX_ROW_CHARS]
    rows = kept + habit_rows
    random.Random(0).shuffle(rows)
    return rows, len(built) - len(kept)


def write_plan(split: Split, rows: list[dict], dropped: int, work: Path, hashes: dict) -> dict:
    """Write lessons, rows and plan.json; return the counts the prereg table must match."""
    for repo, items in split.test.items():
        _jsonl(work / "lessons" / f"{repo.replace('/', '__')}.jsonl", [asdict(i) for i in items])
    _jsonl(work / "meta" / "train.jsonl", rows)
    _jsonl(work / "meta" / "valid.jsonl", rows[:8])
    plan = {
        "test_repos": {repo: len(items) for repo, items in split.test.items()},
        "control_of": split.control_of,
        "meta_train_repos": sorted(split.meta),
        "meta_train_rows": len(rows),
        "meta_rows_dropped_too_long": dropped,
        "shared_key_lesson_ids": shared_keys(split),
        **hashes,
    }
    (work / "plan.json").write_text(json.dumps(plan, indent=1, sort_keys=True))
    return plan


def main() -> None:
    """The plan stage: split, checks, rows and hashes, before any answer exists."""
    import build_lessons  # noqa: PLC0415  (reads the pool)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("plan", "check"))
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--habit-split", type=Path, help="AIDev split.json")
    parser.add_argument("--habit-rows", type=Path, required=True, help="AIDev habits train.jsonl")
    parser.add_argument("--habit-questions", type=Path, help="AIDev held-out habit questions")
    parser.add_argument("--habit-system", type=Path, help="habit system prompt file")
    parser.add_argument("--prereg", help="the frozen prereg, for `check`")
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "check":
        hashes = input_hashes(args.pool, args.habit_rows, args.habit_questions, args.habit_system)
        verify_inputs(hashes)
        provenance = {**scored_run_label(args.prereg), **hashes}
        (args.work / "provenance.json").write_text(json.dumps(provenance, indent=1, sort_keys=True))
        print(json.dumps(provenance, indent=1))
        return
    candidates, _, _ = build_lessons._candidates(args.pool, [])
    habit_split = json.loads(args.habit_split.read_text())
    habit_repos = [repo for repo, split in habit_split.items() if split == "train"]
    split = plan_split(distinct(candidates), habit_repos)
    habit_rows = [json.loads(line) for line in args.habit_rows.read_text().splitlines()]
    rows, dropped = meta_train_rows(split, habit_rows)
    hashes = {
        "pool_index_sha256": pool_index_sha(args.pool),
        "habit_rows_sha256": sha256_of(args.habit_rows),
    }
    counts = write_plan(split, rows, dropped, args.work, hashes)
    print(json.dumps({k: v for k, v in counts.items() if k != "meta_train_repos"}, indent=1))


if __name__ == "__main__":
    main()
