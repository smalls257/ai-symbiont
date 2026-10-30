"""PLUG-AGENT-2: the applies tasks from the committed labels, and the 25 smoke-test tasks.

Smoke tasks are the first 25 applies tasks in sha256 order of `plug-agent-2-smoke:<instance_id>`;
they are excluded from scoring.
Usage: python plug_agent2_smoke_select.py <labels.jsonl> <rows.json> <out-dir>
"""

import hashlib
import json
import sys
from pathlib import Path

SMOKE_TASKS = 25


def applies_tasks(labels_log: Path) -> tuple[list[str], list[dict]]:
    """(tasks with at least one `applies` lesson, the excluded records with their reasons)."""
    found, excluded = [], []
    for line in labels_log.read_text().splitlines():
        record = json.loads(line)
        if "excluded" in record:
            excluded.append(record)
        elif "applies" in record["labels"].values():
            found.append(record["task"])
    return sorted(found), excluded


def smoke_order(task: str) -> str:
    return hashlib.sha256(f"plug-agent-2-smoke:{task}".encode()).hexdigest()


def main() -> None:
    applies, excluded = applies_tasks(Path(sys.argv[1]))
    rows = {row["instance_id"]: row for row in json.loads(Path(sys.argv[2]).read_text())}
    out = Path(sys.argv[3])
    chosen = sorted(applies, key=smoke_order)[:SMOKE_TASKS]
    (out / "smoke-rows.json").write_text(json.dumps([rows[task] for task in chosen]))
    (out / "applies-tasks.json").write_text(
        json.dumps({"applies": applies, "smoke": chosen, "excluded": excluded})
    )
    print(
        json.dumps(
            {"applies": len(applies), "smoke": len(chosen), "excluded_unlabeled": len(excluded)}
        )
    )


if __name__ == "__main__":
    main()
