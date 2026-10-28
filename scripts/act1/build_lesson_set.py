"""Build the Freedoom adapter's Route B training set from played episodes. CPU only, no model.

Reads an episodes directory written by collect_episodes.py (records plus decision logs), turns
mistakes into game lessons, selects the set and writes Route B's layout under WORK/data:
`train/freedoom/train.jsonl` (chat rows), `lessons.jsonl` and `build-counts.json` (counts only).
Prints the counts, never lesson text.

Prevents Silent Fallback: an episode whose records exist without a decision log, a held-out level,
or fewer lessons than `--min-lessons` stops the build with the reason.

Usage: uv run python scripts/act1/build_lesson_set.py --episodes DIR --work WORK [--lessons 40]
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from symbiont.act1.episode import Decision, build_prompt, history_before
from symbiont.act1.game_lessons import lessons_from_history
from symbiont.act1.lesson_rows import Situation, dataset_rows, select_lessons
from symbiont.records.schema import Record, load_jsonl

DECISIONS_SUFFIX = ".decisions.jsonl"
SET_NAME = "freedoom"
# Dispatch target: 20 to 40 lessons. A check may teach at most a quarter of a 40-lesson set.
DEFAULT_LESSONS = 40
DEFAULT_PER_CHECK = 10
DEFAULT_MIN_LESSONS = 20


def episode_files(episodes: Path) -> list[Path]:
    """Record files in level then session order; decision logs are not record files."""
    found = sorted(episodes.glob("*/*.jsonl"))
    return [path for path in found if not path.name.endswith(DECISIONS_SUFFIX)]


def last_run(log: Path) -> list[Decision]:
    """Decisions after the log's last run header: a rerun appends, and its records replaced
    the failed run's. Raises FileNotFoundError when the episode has no decision log.
    """
    decisions: list[Decision] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        entry: dict[str, Any] = json.loads(line)
        if "run_header" in entry:
            decisions = []
            continue
        decisions.append(Decision(**{**entry, "outcomes": tuple(entry["outcomes"])}))
    return decisions


def situations_of(session_id: str, decisions: list[Decision]) -> dict[tuple[str, int], Situation]:
    """The rebuilt game prompt and reply of every decision whose reply was played."""
    return {
        (session_id, decision.index): Situation(
            build_prompt(decision.observation, history_before(decisions, decision.index)),
            decision.reply,
        )
        for decision in decisions
        if decision.status == "ok"
    }


def read_history(episodes: Path) -> tuple[list[Record], dict[tuple[str, int], Situation]]:
    """Every record and every played decision's situation; raises when a decision log is missing."""
    records: list[Record] = []
    situations: dict[tuple[str, int], Situation] = {}
    for path in episode_files(episodes):
        with path.open(encoding="utf-8") as handle:
            records.extend(load_jsonl(handle))
        session_id = path.name.removesuffix(".jsonl")
        log = path.with_name(session_id + DECISIONS_SUFFIX)
        if not log.exists():
            raise FileNotFoundError(f"{path} has no decision log {log.name}")
        situations.update(situations_of(session_id, last_run(log)))
    return records, situations


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def build(episodes: Path, work: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Write the set under work/data; return the counts. Raises ValueError for too few lessons."""
    records, situations = read_history(episodes)
    harvest = lessons_from_history(records)
    chosen = select_lessons(harvest.lessons, args.lessons, args.per_check)
    if len(chosen) < args.min_lessons:
        raise ValueError(f"{len(chosen)} lessons selected; the set needs {args.min_lessons}")
    rows = dataset_rows(chosen, situations)
    data = work / "data"
    _write_jsonl(data / "train" / SET_NAME / "train.jsonl", rows)
    _write_jsonl(data / "lessons.jsonl", [{**asdict(lesson), "card": lesson.card()}
                                          for lesson in chosen])  # fmt: skip
    counts = {
        "episodes": len({record.session_id for record in records}),
        "records": len(records),
        "mistakes": dict(harvest.mistakes),
        "lessons_found": len(harvest.lessons),
        "unresolved_groups": dict(harvest.unresolved),
        "lessons_selected": len(chosen),
        "selected_by_pain": dict(Counter(lesson.pain.value for lesson in chosen)),
        "repeated_selected": sum(lesson.repeats > 1 for lesson in chosen),
        "training_rows": len(rows),
        "situation_rows": len(rows) - 2 * len(chosen),
        "levels": sorted({lesson.level for lesson in chosen}),
    }
    (data / "build-counts.json").write_text(json.dumps(counts, indent=1))
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--lessons", type=int, default=DEFAULT_LESSONS)
    parser.add_argument("--per-check", type=int, default=DEFAULT_PER_CHECK)
    parser.add_argument("--min-lessons", type=int, default=DEFAULT_MIN_LESSONS)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.episodes.expanduser(), args.work.expanduser(), args), indent=1))


if __name__ == "__main__":
    main()
