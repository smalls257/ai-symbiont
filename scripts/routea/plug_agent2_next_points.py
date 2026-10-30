"""PLUG-AGENT-2 next-action test: candidate points mined from Glimmer's own run logs only.

Every Core plain-Glimmer run of every repository (Django included) yields lessons from the runs of
EARLIER tasks of the same repository (task number as the order, a proxy for creation order; never
the task's own runs). The issue text comes from the run's own first message. Spark labels pairs
with the frozen prompt; a point is an occurrence of a failure whose normalized error line equals
an `applies` lesson's. Usage: plug_agent2_next_points.py TRAJS.json BASE OUT-DIR (stage: stores)
"""

import json
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from plug_agent2_core_stores import lessons_of_run
from plug_agent2_pool import STORE_SIZE

PR_DESCRIPTION = re.compile(r"<pr_description>\s*(.*?)\s*</pr_description>", re.DOTALL)
TASK_NUMBER = re.compile(r"-(\d+)$")


def issue_text(messages: list[dict]) -> str:
    """The task statement from the run's own first user message."""
    content = messages[1]["content"]
    found = PR_DESCRIPTION.search(content)
    return (
        (found.group(1) if found else content)
        .removeprefix("Consider the following PR description:")
        .strip()
    )


def repo_of(task: str) -> str:
    return task.rsplit("-", 1)[0].replace("__", "/", 1)


def number_of(task: str) -> int:
    return int(TASK_NUMBER.search(task).group(1))


def store_for(task: str, trajs: dict, lessons: dict) -> list:
    """Distinct lessons of runs on same-repository tasks with a smaller task number."""
    earlier = [t for t in trajs if repo_of(t) == repo_of(task) and number_of(t) < number_of(task)]
    earlier.sort(key=number_of, reverse=True)
    pooled = {(x.failed, x.error): x for t in reversed(earlier) for x in lessons[t]}
    return list(pooled.values())[::-1][:STORE_SIZE]


def main() -> None:
    trajs = json.loads(Path(sys.argv[1]).read_text())
    base, out = Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    lessons = {
        t: [x for run in sorted(r) for x in lessons_of_run(t, base / run)] for t, r in trajs.items()
    }
    rows, stores = [], {}
    for task, runs in sorted(trajs.items()):
        store = store_for(task, trajs, lessons)
        if store:
            first = json.loads((base / sorted(runs)[0]).read_text())["messages"]
            rows.append(
                {"instance_id": task, "repo": repo_of(task), "problem_statement": issue_text(first)}
            )
            stores[task] = {"repo": repo_of(task), "lessons": [asdict(x) for x in store]}
    (out / "rows.json").write_text(json.dumps(rows))
    (out / "stores.json").write_text(json.dumps(stores))
    print(
        json.dumps(
            {
                "tasks": len(trajs),
                "with_store": len(stores),
                "by_repo": dict(Counter(repo_of(t) for t in stores)),
            }
        )
    )


if __name__ == "__main__":
    main()
