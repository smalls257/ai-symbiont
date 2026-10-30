"""PLUG-AGENT-2 Core stores: template lessons from Core's EARLIER plain-Glimmer runs of a repo.

Same lesson builder as the nebius pool, applied to our own runs on public SWE-rebench tasks. A
task's store holds lessons from runs on same-repository tasks created strictly before it.
Usage: python plug_agent2_core_stores.py TRAJS.json SHARDS-DIR OUT-DIR
"""

import hashlib
import json
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from lessons import Lesson, lessons_in_session
from plug import distinct
from plug_agent2_pool import STORE_SIZE, fetch_rows

from symbiont.readers.mini_swe_agent import read_local_run


def as_text_turns(messages: list[dict]) -> list[dict]:
    """Tool-calling turns as the reader's text turns: each bash call becomes a fenced block."""
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


def lessons_of_run(task: str, path: Path) -> list[Lesson]:
    """The lessons one trajectory yields."""
    messages = as_text_turns(json.loads(path.read_text())["messages"])
    row = {
        "trajectory_id": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
        "instance_id": task,
        "messages": messages,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
        handle.write(json.dumps(row) + "\n")
    by_session: dict[str, list] = {}
    for record in read_local_run(Path(handle.name), "local-run"):
        by_session.setdefault(record.session_id, []).append(record)
    Path(handle.name).unlink()
    found = [
        lesson
        for session in by_session.values()
        for lesson in lessons_in_session(session, Counter())
    ]
    return [lesson for group in distinct(found).values() for lesson in group]


def store_of(task: str, rows: dict, lessons: dict[str, list[Lesson]]) -> list[Lesson]:
    """Distinct lessons of runs on same-repository tasks created strictly before `task`."""
    row = rows[task]
    earlier = [
        other for other, found in rows.items()
        if found["repo"] == row["repo"] and str(found["created_at"]) < str(row["created_at"])
    ]  # fmt: skip
    earlier.sort(key=lambda name: (str(rows[name]["created_at"]), name), reverse=True)
    pooled = {(x.failed, x.error): x for name in reversed(earlier) for x in lessons.get(name, [])}
    return list(pooled.values())[::-1][:STORE_SIZE]


def main() -> None:
    trajs = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    rows = {r["instance_id"]: r for r in fetch_rows(sorted(trajs), Path(sys.argv[2]))}
    lessons = {
        task: [x for path in sorted(paths) for x in lessons_of_run(task, Path(path))]
        for task, paths in trajs.items()
        if task in rows
    }
    stores, drops = {}, Counter()
    for task, row in sorted(rows.items()):
        store = store_of(task, rows, lessons)
        if not store:
            drops["no earlier lesson"] += 1
        elif not row["docker_image"]:
            drops["no docker image"] += 1
        else:
            created = str(row["created_at"])
            stores[task] = {
                "repo": row["repo"],
                "created_at": created,
                "lessons": [asdict(x) for x in store],
            }
    (out / "stores.json").write_text(json.dumps(stores))
    (out / "rows.json").write_text(json.dumps([rows[task] for task in stores], default=str))
    summary = {"trajectory_tasks": len(trajs), "rows_found": len(rows), "candidates": len(stores)}
    (out / "summary.json").write_text(json.dumps(summary | {"dropped": dict(drops)}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
