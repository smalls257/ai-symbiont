"""PLUG-AGENT-2 point list: every known mistake in the recorded runs, frozen before any branch.

A point is one occurrence, in one recorded run, of a failure whose normalized error line equals
that of an `applies`-labeled lesson of its task; a later occurrence in the same run is a point too.
The list holds ids, sources, lesson ids and normalized lines, in the fixed sha256 order, with the
probe tasks left out.
Usage: plug_agent2_points.py PROBE.json OUT.json SOURCE:LABELS:STORES:TRAJS:BASE ...
"""

import hashlib
import json
import sys
from pathlib import Path

from plug_agent2_branchpoint import find_branch_points
from plug_agent2_errorline import is_generic_environment
from plug_agent2_measure import known_keys, lesson_key


def order_key(point_id: str) -> str:
    return hashlib.sha256(f"plug-agent-2:{point_id}".encode()).hexdigest()


def points_of_run(
    task: str, run: str, messages: list[dict], labels: dict, lessons: list[dict]
) -> list[dict]:
    """The frozen record of each known mistake in one run."""
    known = known_keys(labels, lessons)
    found = []
    for ordinal, point in enumerate(find_branch_points(messages, known)):
        matching = sorted(
            x["lesson_id"]
            for x in lessons
            if labels.get(x["lesson_id"]) == "applies" and lesson_key(x) == point.key
        )
        found.append(
            {
                "id": f"{task}|{Path(run).name}|{ordinal}",
                "task": task,
                "run": run,
                "ordinal": ordinal,
                "lessons": matching,
                "normalized_line": point.key[0],
                "generic_environment": is_generic_environment(point.key[0]),
            }
        )
    return found


def points_of_source(spec: str, probe: set[str]) -> list[dict]:
    """The points of one source given as SOURCE:LABELS:STORES:TRAJS:BASE (BASE holds the runs)."""
    source, labels_path, stores_path, trajs_path, base = spec.split(":")
    labels = json.loads(Path(labels_path).read_text())["labels"]
    stores = json.loads(Path(stores_path).read_text())
    found = []
    for task, runs in sorted(json.loads(Path(trajs_path).read_text()).items()):
        if task in probe or task not in labels or "applies" not in labels[task].values():
            continue
        for run in sorted(runs):
            messages = json.loads((Path(base) / run).read_text())["messages"]
            points = points_of_run(task, run, messages, labels[task], stores[task]["lessons"])
            found += [point | {"source": source} for point in points]
    return found


def main() -> None:
    probe = set(json.loads(Path(sys.argv[1]).read_text())["probe_points"])
    found = [point for spec in sys.argv[3:] for point in points_of_source(spec, probe)]
    found.sort(key=lambda point: order_key(point["id"]))
    Path(sys.argv[2]).write_text(
        json.dumps({"order": "sha256 of plug-agent-2:<id>", "points": found}, indent=1)
    )
    summary = {"points": len(found), "tasks": len({p["task"] for p in found})}
    print(json.dumps(summary | {"generic": sum(p["generic_environment"] for p in found)}))


if __name__ == "__main__":
    main()
