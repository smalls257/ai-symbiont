"""Build the AIDev review-flag signal, lessons and the Route B habits set; print counts only.

Usage: python scripts/aidev/build.py --data <aidev_v4 dir> --out ~/symbiont-runs/aidev
       [--results results/aidev-lessons.json]

Periphery: reads the local AIDev v4 download (HF hao-li/AIDev, CC-BY-4.0, Hao Li et al., arXiv
2507.15003), writes per-unit labels, lessons and chat rows under `--out` (never tracked), and
counts, ids and labels only to `--results`. Every comment that does not anchor and every unit that
cannot be judged is counted by reason, per agent, so the published rates show what they rest on.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import IO

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import load  # noqa: E402
from flags import Flag, Outcome, Unit, label_pr  # noqa: E402
from hunks import section_name  # noqa: E402
from lessons import Lesson, classify, lesson_id, resolution  # noqa: E402
from order import order_votes  # noqa: E402
from report import results_document  # noqa: E402
from training import Split, assign_splits, held_out_questions, rows_for  # noqa: E402

from symbiont.miner.diffs import added_lines, removed_lines  # noqa: E402

MAX_LESSONS_PER_REPO = 30  # one busy repository must not set the habits of the whole adapter


def nested() -> defaultdict:
    """A counter tree: nested()[a][b][c] += 1."""
    return defaultdict(nested)


class Tally:
    """Every count the run publishes, keyed by agent."""

    def __init__(self) -> None:
        """Start every count at zero."""
        self.signal = nested()
        self.anchoring: dict[str, Counter[str]] = defaultdict(Counter)
        self.miner_agreement: Counter[str] = Counter()
        self.dropped: Counter[str] = Counter()
        self.order: Counter[str] = Counter()
        self.unreadable: Counter[str] = Counter()

    def add_unit(self, agent: str, unit: Unit, last: int, first_review: int | None) -> None:
        """Count a unit under both cuts: after its own commit, and after the first human review."""
        point = unit.human_at if unit.human_at is not None else unit.commit_index
        if unit.flag() is Flag.BOT:
            point = unit.bot_at if unit.bot_at is not None else point
        self._bump("all", agent, unit.flag(), unit.outcome_after(point, last))
        if first_review is not None and _live_at(unit, first_review):
            # A bot-only flag is its own arm: counting it as unflagged would inflate the base rate.
            self._bump("first_review", agent, unit.flag(), unit.outcome_after(first_review, last))

    def _bump(self, cut: str, agent: str, flag: Flag, outcome: Outcome) -> None:
        node = self.signal[cut][agent][flag.value]
        node[outcome.value] = (node[outcome.value] or 0) + 1


def _live_at(unit: Unit, point: int) -> bool:
    if unit.commit_index > point:
        return False
    return all(at is None or at > point for at in (unit.changed_at, unit.unknown_at))


@dataclass(frozen=True)
class PrView:
    """One labeled PR with what lesson-making needs from it."""

    pid: int
    meta: load.PrMeta
    commits: list
    patches: dict
    raws: dict[int, load.RawComment]
    last: int


def content_rule(pr: PrView, raw: load.RawComment, unit: Unit) -> bool:
    """The miner's own review_flag rule: a later patch on the file removes a line the hunk added."""
    flagged = added_lines(raw.diff_hunk)
    start = (unit.human_at or 0) + 1
    later = (pr.patches.get((j, unit.path), "") for j in range(start, pr.last + 1))
    return any(flagged & removed_lines(patch) for patch in later)


def lesson_for(pr: PrView, unit: Unit, raw: load.RawComment, tally: Tally) -> Lesson | None:
    """One lesson for a human-flagged unit, or None with the reason counted."""
    if pr.meta.language != "Python" or not unit.path.endswith(".py"):
        tally.dropped["not_python"] += 1
        return None
    kind = classify(raw.body)
    if kind is None:
        tally.dropped["not_a_general_kind"] += 1
        return None
    fix = resolution(unit, pr.commits, kind)
    if fix is None:
        tally.dropped[f"not_resolved_{kind.value}"] += 1
        return None
    function = section_name(unit.hunk.section) or section_name(raw.diff_hunk.split("\n", 1)[0])
    meta = pr.meta
    return Lesson(lesson_id(pr.pid, unit), meta.repo, meta.agent, kind, unit.path, function, fix)


def label_all(con, meta: dict, tally: Tally, out: Path) -> list[Lesson]:
    """Label every PR with an inline comment; write per-unit labels; return the lessons."""
    bad_hunks: list[int] = []
    comments = load.root_comments(con, bad_hunks)
    tally.unreadable["review_hunk"] = len(bad_hunks)
    bad_patches: list[str] = []
    found: list[Lesson] = []
    with (out / "review_flag_labels.jsonl").open("w") as labels:
        for pid, commits, patches in load.pr_commits(con, set(comments), bad_patches):
            raws = {r.comment.comment_id: r for r in comments[pid]}
            pr = PrView(pid, meta[pid], commits, patches, raws, len(commits) - 1)
            found.extend(label_one(pr, tally, labels))
    tally.unreadable["commit_patch"] = len(bad_patches)
    return found


def label_one(pr: PrView, tally: Tally, labels: IO[str]) -> list[Lesson]:
    """Label one PR, count it, write its unit rows, and return its lessons."""
    labeled = label_pr(pr.commits, [r.comment for r in pr.raws.values()])
    agent = pr.meta.agent
    tally.anchoring[agent].update(labeled.anchoring)
    found = []
    for unit in labeled.units:
        tally.add_unit(agent, unit, pr.last, labeled.first_review)
        labels.write(json.dumps(_label_row(pr.pid, agent, unit, pr.last)) + "\n")
        if unit.human_at is None:
            continue
        raw = pr.raws[min(i for i in unit.comment_ids if pr.raws[i].comment.human)]
        _agree(tally, unit, pr.last, by_content=content_rule(pr, raw, unit))
        lesson = lesson_for(pr, unit, raw, tally)
        if lesson is not None:
            found.append(lesson)
    return found


def _label_row(pid: int, agent: str, unit: Unit, last: int) -> dict:
    point = unit.human_at if unit.human_at is not None else unit.commit_index
    return {
        "pr_id": pid,
        "agent": agent,
        "path": unit.path,
        "commit_index": unit.commit_index,
        "added_lines": len(unit.hunk.added),
        "flag": unit.flag().value,
        "flagged_at": unit.human_at,
        "outcome": unit.outcome_after(point, last).value,
    }


def _agree(tally: Tally, unit: Unit, last: int, *, by_content: bool) -> None:
    outcome = unit.outcome_after(unit.human_at or 0, last)
    if outcome not in (Outcome.CHANGED, Outcome.SURVIVED):
        return
    tracked = "changed" if outcome is Outcome.CHANGED else "survived"
    tally.miner_agreement[f"tracking_{tracked}_content_{'yes' if by_content else 'no'}"] += 1


def capped(lessons: list[Lesson]) -> list[Lesson]:
    """At most MAX_LESSONS_PER_REPO per repository, spread over kinds, in a stable order."""
    by_repo: dict[str, list[Lesson]] = defaultdict(list)
    for lesson in sorted(lessons, key=lambda item: item.lesson_id):
        by_repo[lesson.repo].append(lesson)
    kept = []
    for items in by_repo.values():
        items.sort(key=lambda item: (sum(1 for o in items if o.kind == item.kind), item.lesson_id))
        kept.extend(items[:MAX_LESSONS_PER_REPO])
    return kept


def write_training(lessons: list[Lesson], out: Path) -> dict:
    """Write lessons, chat rows per split, held-out questions and the split; return row counts."""
    routeb = out / "routeb"
    routeb.mkdir(parents=True, exist_ok=True)
    splits = assign_splits(Counter(item.repo for item in lessons))
    by_split: dict[Split, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        by_split[splits[lesson.repo]].append(lesson)
    counts: dict = {}
    for split in Split:
        rows = rows_for(by_split[split])
        _jsonl(routeb / f"{split.value}.jsonl", rows)
        counts[split.value] = {"lessons": len(by_split[split]), "rows": len(rows)}
        counts[split.value]["by_kind"] = dict(Counter(item.kind.value for item in by_split[split]))
    questions = [q for item in by_split[Split.HELD_OUT] for q in held_out_questions(item)]
    _jsonl(routeb / "held_out_questions.jsonl", questions)
    counts["held_out_questions"] = len(questions)
    repos = {repo: split.value for repo, split in splits.items()}
    (routeb / "split.json").write_text(json.dumps(repos, indent=1, sort_keys=True))
    counts["repos"] = dict(Counter(repos.values()))
    _jsonl(out / "lessons.jsonl", [_lesson_row(item, splits[item.repo]) for item in lessons])
    return counts


def _lesson_row(lesson: Lesson, split: Split) -> dict:
    return {
        "lesson_id": lesson.lesson_id,
        "repo": lesson.repo,
        "agent": lesson.agent,
        "kind": lesson.kind.value,
        "split": split.value,
        "text": lesson.text(),
    }


def _jsonl(path: Path, rows: list) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def main() -> None:
    """Run every stage and print the published counts."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    con = load.connect(args.data)
    tally = Tally()
    heads = load.comment_heads(con)
    for pid, facts in load.order_facts(con):
        tally.order.update(order_votes(facts, heads.get(pid, [])))
    meta = load.pr_meta(con)
    found = label_all(con, meta, tally, args.out)
    kept = capped(found)
    training = write_training(kept, args.out)
    document = results_document(tally, found, kept, training)
    text = json.dumps(document, indent=1, sort_keys=True)
    (args.out / "summary.json").write_text(text)
    if args.results:
        args.results.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
