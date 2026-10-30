"""Plug round 4, general judge rows from real repeats: the same normalized error again.

Usage: uv run python scripts/routea/plug_r4_repeat_rows.py build --pool P... --normalizer N \
Usage:   --exclude X... --replay R3_TRAIN --out DIR

A later repeat of an error is a real (situation, lesson) positive, the lesson mined from the
earlier failure's first fix; a hard negative is another lesson of the session. Template text only.
"""

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from lessons import error_line, lessons_in_session  # noqa: E402
from plug_judge import JUDGE_SYSTEM, NO, YES, chat  # noqa: E402
from plug_r4 import judge_text  # noqa: E402
from plug_r4_cont import sentence, with_replay  # noqa: E402
from plug_r4_recur import repo_of  # noqa: E402
from plug_r4_repeats import load_normalizer  # noqa: E402
from warm_start import _jsonl, _read_jsonl  # noqa: E402

from symbiont.miner.commands import normalise_command  # noqa: E402
from symbiont.records.schema import Kind  # noqa: E402

SEED = 0
EVENTS_PER_REPO = 40  # one repository cannot dominate the general model
REPLAY_SHARE = 0.25


def lesson_id_of(record) -> str:
    """The id `lessons` gives the lesson mined from this failed command."""
    return hashlib.sha1(f"{record.session_id}:{record.step}".encode()).hexdigest()[:12]


def failures_of(session, normalizer) -> list:
    """(normalized error, record) for each failed command naming an error, in order."""
    found = []
    for record in session:
        if record.kind == Kind.COMMAND and record.exit_code and record.command:
            line = error_line(record.raw)
            key = normalizer.normalize_error_line(line) if line else ""
            if key:
                found.append((key, record))
    return found


def situation_of_record(record, repo: str) -> str:
    """The failure in the round 3 situation wording."""
    from lessons import shown_command  # noqa: PLC0415

    shown = shown_command(record.command)
    return sentence(shown, repo, normalise_command(shown)[1], error_line(record.raw) or "")


def session_events(session, normalizer, repo: str) -> list[dict]:
    """Within-session repeats: (later situation, first lesson, a hard-negative lesson)."""
    lessons = {x.lesson_id: x for x in lessons_in_session(session, Counter())}
    failures = failures_of(session, normalizer)
    keys = {lesson_id_of(r): k for k, r in failures}
    first: dict[str, str] = {}
    events = []
    for key, record in failures:
        mine = lesson_id_of(record)
        if key in first and first[key] in lessons:
            others = [x for lid, x in sorted(lessons.items()) if keys.get(lid) != key]
            events.append(
                {
                    "source": "within",
                    "situation": situation_of_record(record, repo),
                    "lesson": lessons[first[key]],
                    "negative": others[0] if others else None,
                }
            )
        first.setdefault(key, mine)
    return events


def cross_events(runs: list, normalizer, repo: str) -> list[dict]:
    """Across sessions of one task: a later session's failure whose key an earlier session's
    lesson has."""
    keyed = []
    for session in runs:
        lessons = {x.lesson_id: x for x in lessons_in_session(session, Counter())}
        by_key = {
            k: lessons[lesson_id_of(r)]
            for k, r in failures_of(session, normalizer)
            if lesson_id_of(r) in lessons
        }
        keyed.append((session, by_key))
    events = []
    for index, (session, _) in enumerate(keyed):
        known = {k: x for _, by in keyed[:index] for k, x in by.items()}
        for key, record in failures_of(session, normalizer):
            if key in known:
                events.append(
                    {
                        "source": "cross",
                        "situation": situation_of_record(record, repo),
                        "lesson": known[key],
                        "negative": next((x for k, x in known.items() if k != key), None),
                    }
                )
    return events


def event_rows(event: dict) -> list[dict]:
    """A yes row, and a no row when a hard negative exists."""
    rows = [chat(JUDGE_SYSTEM, judge_text(event["situation"], event["lesson"].text()), YES)]
    if event["negative"] is not None:
        rows.append(
            chat(JUDGE_SYSTEM, judge_text(event["situation"], event["negative"].text()), NO)
        )
    return rows


def capped(events: list[dict], seed: int = SEED) -> list[dict]:
    """At most EVENTS_PER_REPO events, seeded."""
    rng = random.Random(seed)
    return rng.sample(events, min(EVENTS_PER_REPO, len(events)))


def build_events(pools: list[Path], normalizer, excluded: set[str]) -> dict[str, list[dict]]:
    """repo -> its repeat events from every non-excluded session (each session id once)."""
    import build_lessons  # noqa: PLC0415  (reads the exports)

    seen: set[str] = set()
    by_repo: dict[str, list] = defaultdict(list)
    by_task: dict[tuple, list] = defaultdict(list)
    for pool in pools:
        for session in build_lessons._sessions(pool, []):
            repo, sid = repo_of(session), session[0].session_id
            if repo in excluded or sid in seen:
                continue
            seen.add(sid)
            by_repo[repo] += session_events(session, normalizer, repo)
            by_task[(repo, session[0].task_id)].append(session)
    for (repo, _), runs in by_task.items():
        if len(runs) > 1:
            by_repo[repo] += cross_events(runs, normalizer, repo)
    return {repo: capped(events) for repo, events in by_repo.items() if events}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("build",))
    parser.add_argument("--pool", type=Path, nargs="+", required=True)
    parser.add_argument("--normalizer", type=Path, required=True)
    parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    excluded: set[str] = set()
    for path in args.exclude:
        excluded |= set(json.loads(path.read_text()))
    normalizer, digest = load_normalizer(args.normalizer)
    events = build_events(args.pool, normalizer, excluded)
    rows = [row for evs in events.values() for event in evs for row in event_rows(event)]
    random.Random(SEED).shuffle(rows)
    mixed = with_replay(rows, _read_jsonl(args.replay), REPLAY_SHARE)
    _jsonl(args.out / "train.jsonl", mixed)
    _jsonl(args.out / "valid.jsonl", mixed[:8])
    manifest = {
        "normalizer_sha256": digest,
        "repos": len(events),
        "events": sum(map(len, events.values())),
        "by_source": dict(Counter(e["source"] for evs in events.values() for e in evs)),
        "repeat_rows": len(rows),
        "total_rows": len(mixed),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
