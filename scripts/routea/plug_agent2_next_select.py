"""PLUG-AGENT-2 next-action runs: which Plug-pool tasks get a plain Glimmer run for mining.

Applies-labeled tasks from many repositories, preferring repositories with several labeled
lessons: repositories by total `applies` lessons (then name), at most PER_REPO tasks each (the
tasks with the most), until COUNT tasks. Smoke tasks already run are left out.
Usage: plug_agent2_next_select.py LABELS.json ROWS.json SMOKE-ROWS.json OUT.json
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

COUNT = 50
PER_REPO = 2


def applies_count(labels: dict[str, str]) -> int:
    return sum(value == "applies" for value in labels.values())


def choose(labels: dict[str, dict], skip: set[str]) -> list[str]:
    """Task ids: top tasks of the repositories with the most applies lessons, PER_REPO each."""
    by_repo: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for task, found in labels.items():
        if task not in skip and applies_count(found):
            by_repo[task.rsplit("-", 1)[0]].append((-applies_count(found), task))
    repos = sorted(by_repo, key=lambda repo: (-sum(-n for n, _ in by_repo[repo]), repo))
    chosen: list[str] = []
    for repo in repos:
        chosen += [task for _, task in sorted(by_repo[repo])[:PER_REPO]]
    return chosen[:COUNT]


def main() -> None:
    labels = json.loads(Path(sys.argv[1]).read_text())["labels"]
    rows = {r["instance_id"]: r for r in json.loads(Path(sys.argv[2]).read_text())}
    skip = {r["instance_id"] for r in json.loads(Path(sys.argv[3]).read_text())}
    chosen = choose(labels, skip)
    Path(sys.argv[4]).write_text(json.dumps([rows[task] for task in chosen]))
    print(json.dumps({"tasks": len(chosen), "repos": len({t.rsplit("-", 1)[0] for t in chosen})}))


if __name__ == "__main__":
    main()
