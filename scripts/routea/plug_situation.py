"""Plug situation test: an agent's current situation and many lessons; pick, note, or stay silent.

Usage: uv run python scripts/routea/plug_situation.py build --pool P --test-repos PLAN --work W
Usage: uv run python scripts/routea/plug_situation.py score --work W --arms a1 a2v --out F
Usage: uv run python scripts/routea/plug_situation.py narrow --source W --keep 5 --work W5
Usage: uv run python scripts/routea/plug_situation.py pilot-report --source W --work W5 --arms A
Usage: uv run python scripts/routea/plug_situation.py ranker-answers --work W

Each lesson gives a pick item (its situation, PROMPT_LESSONS lessons including it) and a silence
item (the same prompt without it). Distractors never share the lesson's failure key; the ranker's
top lessons are shuffled per item so their order gives nothing away. Scoring is whole-token
containment of a fix, excusing lessons the right fix itself names, plus abstention.
"""

import argparse
import json
import math
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import Lesson  # noqa: E402
from plug import abstains, distinct, fold  # noqa: E402
from questions import lessons_prompt  # noqa: E402
from warm_start import _jsonl, _read_jsonl, paired_gain  # noqa: E402

PROMPT_LESSONS = 60  # within the 50-100 range the owner set; fits the 1B context at ~5k tokens
_EDGE = ".,;:!?()[]{}<>"  # punctuation stripped from token edges before whole-token matching
ASK = (
    "The agent is now doing this:\n{situation}\n"
    "Write one note for the agent, or say that no lesson applies."
)


@dataclass(frozen=True)
class Item:
    """A situation, the lessons in its prompt, and the lesson that applies, if any."""

    item_id: str
    situation: str
    prompt_lessons: tuple[Lesson, ...]
    applies: Lesson | None
    excused: tuple[str, ...] = ()  # lessons the applicable fix itself names: never a wrong pick


def situation_of(lesson: Lesson) -> str:
    """What the agent is doing now, in the lesson's own short fields."""
    return f"Ran `{lesson.failed}` in {lesson.repo} (file {lesson.file}). It failed: {lesson.error}"


def build_items(test: dict[str, list[Lesson]], pool: Sequence[Lesson], seed: int = 0) -> list[Item]:
    """A pick and a silence item per test lesson. Distractors: the repo's other lessons, then
    `pool` lessons of other repos; none shares the lesson's (error class, fix tokens) key."""
    rng = random.Random(seed)
    items = []
    for repo, lessons in sorted(test.items()):
        for lesson in lessons:
            others = [o for o in pool if o.repo != repo and key_of(o) != key_of(lesson)]
            shown = _shown(lesson, lessons, others, rng)
            silent = tuple(other for other in shown if other is not lesson)
            situation = situation_of(lesson)
            excused = tuple(o.lesson_id for o in silent if names_fix(lesson.fix, o))
            items.append(Item(f"{lesson.lesson_id}-pick", situation, shown, lesson, excused))
            items.append(Item(f"{lesson.lesson_id}-silence", situation, silent, None))
    return items


def key_of(lesson: Lesson) -> tuple[str, tuple[str, ...]]:
    """What makes two lessons the same failure."""
    return lesson.error_class, lesson.added


def _shown(lesson, lessons, others, rng) -> tuple[Lesson, ...]:
    same_repo = [other for other in lessons if other is not lesson]
    needed = PROMPT_LESSONS - len(same_repo) - 1
    if needed < 0 or len(others) < needed:
        raise ValueError(f"cannot fill {PROMPT_LESSONS} lessons for {lesson.repo}")
    shown = [*same_repo, *rng.sample(others, needed), lesson]
    rng.shuffle(shown)
    return tuple(shown)


_WORD = re.compile(r"[A-Za-z_][\w.\-/]+")


def words(text: str) -> set[str]:
    """Lower-case identifiers, paths and command words."""
    return set(_WORD.findall(text.lower()))


def lexical_rank(item: Item) -> list[Lesson]:
    """The item's lessons, best first, by inverse-document-frequency overlap with the situation."""
    situation = words(item.situation)
    docs = {
        lesson.lesson_id: words(
            f"{lesson.repo} {lesson.program} {lesson.file} {lesson.failed} {lesson.error_class}"
        )
        for lesson in item.prompt_lessons
    }
    df = Counter(word for doc in docs.values() for word in doc)

    def score(lesson: Lesson) -> float:
        return sum(math.log(len(docs) / df[word]) for word in docs[lesson.lesson_id] & situation)

    return sorted(item.prompt_lessons, key=lambda lesson: (-score(lesson), lesson.lesson_id))


def narrowed(item: Item, keep: int, seed: int = 0) -> Item:
    """The ranker's top `keep` lessons in a per-item shuffled order (the ranker's order would give
    the answer away). The applicable lesson stays the answer even if the ranker dropped it."""
    top = lexical_rank(item)[:keep]
    random.Random(f"{seed}:{item.item_id}").shuffle(top)
    shown = {lesson.lesson_id for lesson in top}
    excused = tuple(lesson_id for lesson_id in item.excused if lesson_id in shown)
    return Item(item.item_id, item.situation, tuple(top), item.applies, excused)


def ranker_answer(item: Item) -> str:
    """The ranker alone: its top lesson's note, whatever the situation."""
    return lexical_rank(item)[0].text()


def prompt_row(item: Item) -> dict:
    """The question row `answer_questions.py` reads; the lessons go in as the context file."""
    return {"question_id": item.item_id, "text": ASK.format(situation=item.situation)}


def context_of(item: Item) -> str:
    """The item's system prompt: every lesson in its prompt."""
    return lessons_prompt(list(item.prompt_lessons))


def tokens_of(text: str) -> list[str]:
    """Folded text split on whitespace, edge punctuation stripped."""
    return [stripped for word in fold(text).split() if (stripped := word.strip(_EDGE))]


def contains(haystack: Sequence[str], phrase: Sequence[str]) -> bool:
    """`phrase` occurs as a contiguous run of whole tokens in `haystack`."""
    size = len(phrase)
    return size > 0 and any(
        list(haystack[i : i + size]) == list(phrase) for i in range(len(haystack) - size + 1)
    )


def names_fix(answer: str, lesson: Lesson) -> bool:
    """The answer carries the lesson's fix as whole tokens: every added token, or the command."""
    found = tokens_of(answer)
    every_token = all(contains(found, tokens_of(token)) for token in lesson.added)
    return every_token or contains(found, tokens_of(lesson.fix))


def verdict(item: Item, answer: str) -> dict[str, bool]:
    """Pick, useful note, wrong pick and silence for one answer."""
    wrong = any(
        names_fix(answer, other)
        for other in item.prompt_lessons
        if other is not item.applies and other.lesson_id not in item.excused
    )
    if item.applies is None:
        return {"silent": abstains(answer) and not wrong, "wrong_pick": wrong}
    picked = names_fix(answer, item.applies)
    useful = picked and item.applies.error_class in fold(answer)
    return {"pick": picked and not wrong, "useful": useful and not wrong, "wrong_pick": wrong}


def rates(items: Sequence[Item], answers: dict[str, str]) -> dict[str, float]:
    """Pick, useful and wrong-pick over pick items; silence over silence items."""
    picks = [verdict(i, answers[i.item_id]) for i in items if i.applies is not None]
    quiet = [verdict(i, answers[i.item_id]) for i in items if i.applies is None]
    if not picks or not quiet:
        raise ValueError("a repo needs pick and silence items")
    return {
        "pick": sum(v["pick"] for v in picks) / len(picks),
        "useful": sum(v["useful"] for v in picks) / len(picks),
        "wrong_pick": sum(v["wrong_pick"] for v in picks + quiet) / (len(picks) + len(quiet)),
        "silence": sum(v["silent"] for v in quiet) / len(quiet),
    }


def item_record(item: Item) -> dict:
    """An item as one JSON row: what the answerer reads and what the scorer needs."""
    return {
        **prompt_row(item),
        "context": context_of(item),
        "situation": item.situation,
        "prompt_lessons": [asdict(lesson) for lesson in item.prompt_lessons],
        "applies": asdict(item.applies) if item.applies else None,
        "excused": list(item.excused),
    }


def _shown_applies(record: dict) -> bool:
    if record["applies"] is None:
        return False
    return any(
        row["lesson_id"] == record["applies"]["lesson_id"] for row in record["prompt_lessons"]
    )


def item_from(record: dict) -> Item:
    """The Item a record was written from."""

    def lesson(row: dict) -> Lesson:
        return Lesson(**{**row, "added": tuple(row["added"])})

    applies = lesson(record["applies"]) if record["applies"] else None
    shown = tuple(lesson(row) for row in record["prompt_lessons"])
    if applies is not None:
        shown = tuple(applies if other.lesson_id == applies.lesson_id else other for other in shown)
    excused = tuple(record["excused"])
    return Item(record["question_id"], record["situation"], shown, applies, excused)


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


def ranker_recall(items: Sequence[Item], depths: Sequence[int] = (1, 3, 5, 10)) -> dict[str, float]:
    """Share of pick items whose applicable lesson the ranker puts in its top k."""
    picks = [item for item in items if item.applies is not None]
    positions = [
        [lesson.lesson_id for lesson in lexical_rank(item)].index(item.applies.lesson_id)
        for item in picks
    ]
    return {
        f"recall_at_{depth}": sum(p < depth for p in positions) / len(picks) for depth in depths
    }


def pick_item_abstention(items: Sequence[Item], answers: dict[str, str]) -> float:
    """Share of pick items the reader answered by saying no lesson applies."""
    picks = [item for item in items if item.applies is not None]
    return sum(abstains(answers[item.item_id]) for item in picks) / len(picks)


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
    kept = sum(1 for row in rows if _shown_applies(row))
    print(json.dumps({"items": len(rows), "applicable_kept": kept}))


def _stage_ranker(args: argparse.Namespace) -> None:
    rows = [
        {"question_id": r["question_id"], "answer": ranker_answer(item_from(r))}
        for r in _read_jsonl(args.work / "items.jsonl")
    ]
    _jsonl(args.work / "answers" / "ranker.jsonl", rows)
    print(json.dumps({"answers": len(rows)}))


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
