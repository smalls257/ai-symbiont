"""Plug round 4: real recurrences of a mistake in a later, different task of the same repository.

Usage: uv run python scripts/routea/plug_r4_recur.py tasks --nebius D... --runs R --out tasks.json
Usage: uv run python scripts/routea/plug_r4_recur.py count --nebius D... --runs R --dates T...
Usage:   --out counts.json

A recurrence is a failed command in a later task whose exact (shown command, error line) matches
a lesson mined from an earlier, different task of the same repository (the loose key normalizes
the command instead). Distinct (later task, key) pairs count once. Sources: the nebius OpenHands
exports on disk, deduplicated by session, and our own mini-SWE-agent runs (`read_local_run`, public
tasks only; never Spark-bound here). Counts and ids only.
"""

import argparse
import hashlib
import json
import pickle
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from build_lessons import _sessions  # noqa: E402
from lessons import error_line, lessons_in_session, shown_command  # noqa: E402

from symbiont.miner.commands import normalise_command  # noqa: E402
from symbiont.readers.mini_swe_agent import PUBLIC_BENCHMARK_REPOS, read_local_run  # noqa: E402
from symbiont.records.schema import Kind, Record  # noqa: E402

TASK_IN_PATH = re.compile(r"([A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+)")
KEYS = ("exact", "loose")


def nebius_sessions(directories: list[Path]) -> Iterator[list[Record]]:
    """Every readable session of the exports, each session id once."""
    seen: set[str] = set()
    for directory in directories:
        for session in _sessions(directory, []):
            if session and session[0].session_id not in seen:
                seen.add(session[0].session_id)
                yield session


def as_text_turns(messages: list[dict]) -> list[dict]:
    """Tool-calling turns (mini-swe-agent 1.1) as the reader's text turns: each bash tool call
    becomes a fenced block in the assistant's text, each tool result a user observation (its
    <returncode> tag kept); the final `exit` message is dropped."""
    found = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            found.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            calls = [
                json.loads(c["function"]["arguments"]) for c in message.get("tool_calls") or []
            ]
            blocks = "".join(
                f"\n```bash\n{call['command']}\n```" for call in calls if "command" in call
            )
            found.append({"role": "assistant", "content": (message.get("content") or "") + blocks})
        elif role in ("system", "user"):
            found.append({"role": role, "content": message["content"]})
    return found


def run_sessions(root: Path) -> Iterator[list[Record]]:
    """Our own runs' sessions (each distinct file once), read as public-task local runs."""
    rows, seen = [], set()
    for path in sorted(root.rglob("*.traj.json")):
        found = TASK_IN_PATH.search(str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if found is None or digest in seen:
            continue
        if found.group(1).rsplit("-", 1)[0].replace("__", "/", 1) not in PUBLIC_BENCHMARK_REPOS:
            continue  # the local-run reader takes public benchmark tasks only
        seen.add(digest)
        messages = as_text_turns(json.loads(path.read_text())["messages"])
        rows.append(
            {"trajectory_id": digest[:16], "instance_id": found.group(1), "messages": messages}
        )
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)
    by_session: dict[str, list[Record]] = {}
    for record in read_local_run(Path(handle.name), "local-run"):
        by_session.setdefault(record.session_id, []).append(record)
    Path(handle.name).unlink()
    yield from by_session.values()


def keys_of(command: str, error: str) -> dict[str, tuple]:
    """The exact and loose keys of one failure."""
    shown = shown_command(command)
    return {"exact": (shown, error), "loose": (normalise_command(shown), error)}


def session_events(session: list[Record]) -> tuple[list[dict], list[dict]]:
    """A session's failures (keys) and its lessons' failures (keys)."""
    failures = []
    for record in session:
        if record.kind == Kind.COMMAND and record.exit_code and record.command:
            error = error_line(record.raw)
            if error:
                failures.append(keys_of(record.command, error))
    lessons = [
        keys_of(lesson.failed, lesson.error) for lesson in lessons_in_session(session, Counter())
    ]
    return failures, lessons


def repo_of(session: list[Record]) -> str:
    """The repository of a session, from its task id (`owner__name-123`)."""
    return session[0].task_id.rsplit("-", 1)[0].replace("__", "/", 1)


def by_repo(sessions) -> dict[str, dict[str, dict[str, set]]]:
    """repo -> task -> {"failures:<key>": keys, "lessons:<key>": keys} over all its sessions."""
    found: dict[str, dict[str, dict[str, set]]] = {}
    for session in sessions:
        failures, lessons = session_events(session)
        slots = found.setdefault(repo_of(session), {}).setdefault(session[0].task_id, {})
        for key in KEYS:
            slots.setdefault(f"failures:{key}", set()).update(f[key] for f in failures)
            slots.setdefault(f"lessons:{key}", set()).update(lesson[key] for lesson in lessons)
    return found


def recurrences(tasks: dict[str, dict[str, set]], dates: dict[str, str], key: str) -> int:
    """Distinct (later task, key) failures that an earlier, different task's lesson has."""
    order = sorted((task for task in tasks if task in dates), key=lambda task: (dates[task], task))
    earlier: set = set()
    found = 0
    for task in order:
        found += len(tasks[task][f"failures:{key}"] & earlier)
        earlier |= tasks[task][f"lessons:{key}"]
    return found


def source_counts(repos: dict, dates: dict[str, str]) -> dict:
    """Per key: recurrences, repos with one, and the tasks left out for having no date."""
    undated = sum(task not in dates for tasks in repos.values() for task in tasks)
    found = {"repos": len(repos), "tasks": sum(map(len, repos.values())), "undated_tasks": undated}
    for key in KEYS:
        per = {repo: recurrences(tasks, dates, key) for repo, tasks in repos.items()}
        found[key] = {
            "recurrences": sum(per.values()),
            "repos_with_one": sum(n > 0 for n in per.values()),
            "per_repo": {repo: n for repo, n in sorted(per.items()) if n},
        }
    return found


def sources(args: argparse.Namespace) -> dict[str, dict]:
    """The two sources' repositories, read once and cached (the exports are several GB)."""
    if args.cache.exists():
        return pickle.loads(args.cache.read_bytes())
    found = {
        "nebius": by_repo(nebius_sessions(args.nebius)),
        "own_runs": by_repo(run_sessions(args.runs)),
    }
    args.cache.write_bytes(pickle.dumps(found))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("tasks", "count"))
    parser.add_argument("--nebius", type=Path, nargs="+", required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--dates", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True, help="keys read from the sessions")
    args = parser.parse_args()
    found = sources(args)
    if args.stage == "tasks":  # the task list `fresh_task_dates.py` reads
        repos = [
            {"repo": r, "tasks": sorted(t)} for part in found.values() for r, t in part.items()
        ]
        args.out.write_text(json.dumps({"repos": repos}))
        print(json.dumps({"tasks": sum(len(r["tasks"]) for r in repos)}))
        return
    dates: dict[str, str] = {}
    for path in args.dates:
        dates |= json.loads(path.read_text())
    counts = {name: source_counts(repos, dates) for name, repos in found.items()}
    args.out.write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
