"""Plug round 4, richer situations: each situation gains the tail of the failed command's output,
and the round-3 mix is rebuilt with it so one judge can be trained and read on the same form.

Round 3's situation already holds the command, the repository, the file and one error line; the
only addition here is up to TAIL_LINES lines of real output. A lesson whose output is not found
raises, never trains or scores on the short form unnoticed.
"""

import hashlib
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from build_lessons import _sessions  # noqa: E402
from plug_judge import judge_mix  # noqa: E402
from plug_r2_rows import PHRASINGS, phrase  # noqa: E402
from plug_r3 import source_of  # noqa: E402
from plug_r3_run import load_items, write_items  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

from symbiont.records.schema import Kind  # noqa: E402

TAIL_LINES = 5
TAIL_CHARS = 400
SHORTLIST = 10


class MissingOutputError(KeyError):
    """A lesson whose failed command's output was not found in the pool."""


def output_tails(pool: Path, wanted: set[str]) -> dict[str, str]:
    """lesson id -> the last TAIL_LINES non-empty output lines of the command it was mined from."""
    found = {}
    for session in _sessions(pool, []):
        for record in session:
            if record.kind != Kind.COMMAND or not record.exit_code:
                continue
            lesson_id = hashlib.sha1(f"{record.session_id}:{record.step}".encode()).hexdigest()[:12]
            if lesson_id in wanted:
                lines = [line for line in record.raw.splitlines() if line.strip()]
                found[lesson_id] = "\n".join(lines[-TAIL_LINES:])[-TAIL_CHARS:]
    missing = wanted - set(found)
    if missing:
        raise MissingOutputError(
            f"{len(missing)} lessons without output, e.g. {sorted(missing)[:3]}"
        )
    return found


def with_tail(situation: str, tail: str) -> str:
    """A situation plus its output tail."""
    return f"{situation}\nOutput:\n{tail}"


def tailed_phrase(template: str, tails: dict[str, str], lesson) -> str:
    """One round-3 phrasing of the lesson's situation, plus its output tail."""
    return with_tail(phrase(template, lesson), tails[lesson.lesson_id])


def tailed_items(items: list, tails: dict[str, str], source) -> list:
    """The items with each situation followed by its source lesson's output tail."""
    return [replace(i, situation=with_tail(i.situation, tails[source(i).lesson_id])) for i in items]


def rich_bundle(pool: Path, work: Path, out: Path, habit_rows: Path) -> dict:
    """The rich round-3 mix from meta-train items and the rich scored items with their queries."""
    meta_items, _ = load_items(work, "trained")
    scored, _ = load_items(work, "scored")
    meta = [item.applies for item in meta_items if item.applies is not None]
    lessons = meta + [item.applies for item in scored if item.applies is not None]
    tails = output_tails(pool, {lesson.lesson_id for lesson in lessons})
    source = source_of(lessons)
    phrasings = [partial(tailed_phrase, template, tails) for template in PHRASINGS]
    rich_meta = tailed_items(meta_items, tails, source)
    mix = judge_mix(rich_meta, SHORTLIST, phrasings, source_of(meta), _read_jsonl(habit_rows))
    _jsonl(out / "rows" / "train.jsonl", mix["rows"])
    _jsonl(out / "rows" / "valid.jsonl", mix["rows"][:8])
    write_items(out, "scored", tailed_items(scored, tails, source), lessons)
    return mix["counts"]
