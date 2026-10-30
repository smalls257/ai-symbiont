"""PLUG-AGENT-2 timing exploration (no claim): can Plug spot the moment before a known mistake?

At every assistant step of recorded Glimmer runs, only what is visible before the command runs is
Plug's situation. It speaks when ranker (10.0) and judge (0.96, 3-seed mean) agree on a lesson;
speech is scored against the frozen known-mistake marks. Usage: plug_agent2_timing.py DATA OUT.json
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

from lessons import Lesson
from plug_agent2_branchpoint import find_branch_points
from plug_agent2_keys import RETURNCODE, Key, executed_actions
from plug_agent2_measure import known_keys, lesson_key
from plug_agent_notes import failure_of
from plug_judge import JUDGE_SYSTEM, pair_prompt, shortlist
from plug_r3 import ranker_choices
from plug_situation import Item

from symbiont.miner.commands import normalise_command

RANKER_THRESHOLD = 10.0
JUDGE_THRESHOLD = 0.96
NEAR = 3
JUDGE_URL = "http://127.0.0.1:8791/score"


def situation_of(command: str, repo: str, previous_error: str | None) -> str:
    """Round 3's wording, turned to the future: the command is planned, not yet run."""
    program, target = normalise_command(command)
    text = f"About to run `{command}` in {repo} (file {target})."
    return text + (f" The previous command failed: {previous_error}" if previous_error else "")


def judge_scores(pairs: list[dict]) -> list[float]:
    body = json.dumps({"pairs": pairs}).encode()
    request = urllib.request.Request(JUDGE_URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as reply:  # noqa: S310 loopback judge
        return json.loads(reply.read())["p_yes"]


def speaks(item: Item) -> str | None:
    """The lesson id Plug speaks with at this step, or None."""
    choice = ranker_choices([item], RANKER_THRESHOLD)[0]
    if choice.lesson_id is None:
        return None
    candidates = shortlist(item, 10)
    pairs = [{"system": JUDGE_SYSTEM, "prompt": pair_prompt(item.situation, x)} for x in candidates]
    best, lesson = max(zip(judge_scores(pairs), candidates, strict=True), key=lambda pair: pair[0])
    return (
        lesson.lesson_id
        if best >= JUDGE_THRESHOLD and lesson.lesson_id == choice.lesson_id
        else None
    )


def previous_error(step_output: str, command: str) -> str | None:
    """The error line of a failed command, None when it passed or names no error."""
    code = RETURNCODE.search(step_output)
    failure = failure_of(command, int(code.group(1)) if code else None, step_output)
    return failure.error if failure else None


def step_speech(
    messages: list[dict], repo: str, store: tuple[Lesson, ...]
) -> dict[int, str | None]:
    """Turn index to the lesson Plug speaks with just before that turn's first command."""
    result: dict[int, str | None] = {}
    error = None
    for step in executed_actions(messages):
        turn = step.model_calls - 1
        if step.action_index == 0:
            result[turn] = speaks(
                Item(f"t{turn}", situation_of(step.command, repo, error), store, None)
            )
        error = previous_error(step.output, step.command)
    return result


def marks_of(
    messages: list[dict], known: frozenset[Key], lessons: list[dict], labels: dict
) -> list[tuple[int, set]]:
    """(turn, applicable lesson ids) of every known mistake in the run (the frozen marks)."""
    found = []
    for point in find_branch_points(messages, known):
        right = {
            x["lesson_id"]
            for x in lessons
            if labels.get(x["lesson_id"]) == "applies" and lesson_key(x) == point.key
        }
        found.append((point.model_calls, right))
    return found


def score(speech: dict[int, str | None], marks: list[tuple[int, set]]) -> dict:
    """Hits, early or late within NEAR turns, misses, and false alarms for one run."""
    spoken = {turn: lesson for turn, lesson in speech.items() if lesson}
    used: set[int] = set()
    hit = near = miss = 0
    for turn, right in marks:
        if spoken.get(turn) in right:
            hit += 1
            used.add(turn)
            continue
        close = [
            t for t in range(turn - NEAR, turn + NEAR + 1) if t != turn and spoken.get(t) in right
        ]
        near += bool(close)
        miss += not close
        used.update(close)
    return {
        "marks": len(marks),
        "hits": hit,
        "early_late": near,
        "misses": miss,
        "speaks": len(spoken),
        "false_alarms": len(spoken) - len(used),
        "steps": len(speech),
    }


def lessons_of(rows: list[dict]) -> tuple[Lesson, ...]:
    return tuple(Lesson(**{**x, "added": tuple(x["added"])}) for x in rows)


def runs_of(data: Path) -> list[tuple[str, Path, dict, dict]]:
    """(source, trajectory, labels, stores-entry) for every recorded Glimmer run with labels."""
    sets = {
        "core": (
            data / "plug2/results/plug-agent-2-core-labels.json",
            data / "plug2/out-core/stores.json",
        ),
        "core-all": (data / "plug2/next-labels.json", data / "plug2/next/stores.json"),
        "own": (data / "plug2/results/plug-agent-2-labels.json", data / "plug2/out/stores.json"),
    }
    loaded = {
        k: (json.loads(a.read_text())["labels"], json.loads(b.read_text()))
        for k, (a, b) in sets.items()
    }
    found = []
    for task, files in json.loads((data / "plug2/core-trajs.json").read_text()).items():
        source = "core" if task in loaded["core"][0] else "core-all"
        if task in loaded[source][0]:
            found += [
                (source, data / "core" / f, loaded[source][0][task], loaded[source][1][task])
                for f in files
            ]
    for folder in ("next-runs/traj", "smoke25/traj"):
        for path in sorted((data / "plug2" / folder).glob("*.traj.json")):
            task = path.name.removesuffix(".traj.json")
            if task in loaded["own"][0]:
                found.append(("own", path, loaded["own"][0][task], loaded["own"][1][task]))
    return found


def main() -> None:
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    totals: dict[str, dict] = {}
    for source, path, labels, entry in runs_of(data)[
        : int(os.environ.get("TIMING_LIMIT", "0")) or None
    ]:
        messages = json.loads(path.read_text())["messages"]
        marks = marks_of(messages, known_keys(labels, entry["lessons"]), entry["lessons"], labels)
        result = score(step_speech(messages, entry["repo"], lessons_of(entry["lessons"])), marks)
        bucket = totals.setdefault(source, {"runs": 0})
        bucket["runs"] += 1
        for key, value in result.items():
            bucket[key] = bucket.get(key, 0) + value
    out.write_text(json.dumps(totals, indent=1))
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
