"""Turn real mini-SWE-agent trajectories of the lesson-in-prompt pilot into demo-replay-v1 files.

Every number is read from a trajectory (usage, timings, return codes), totals are summed from the
steps, and an unreadable step raises TrajectoryError. Tag heuristics: dashboard/AGENTS.md.

    uv run python scripts/routea/build_pilot_replay.py IN_DIR OUT_DIR
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pilot_step_tags import (  # noqa: E402  (the sibling module is found through the path line above)
    SUBMIT_MARK,
    RunMemory,
    action_label,
    failed_test_run,
    mistake_tag,
)

SCHEMA = "demo-replay-v1"
SOURCE_LINE = (
    "real runs, one per arm: plain hit the 50-step cap; "
    "lesson in prompt (pilot), not the LoRA; no classifier"
)
PLAIN_SUBTITLE = "Glimmer, no adapter, no notes"
LESSON_LABEL = "Glimmer with a lesson in the prompt (pilot)"
LESSON_SUBTITLE = "Glimmer, lesson in the prompt (pilot), no adapter"
SOLVED = "solved"
NOT_SOLVED = "not solved"
LESSON_SOURCE = "lesson in prompt (pilot)"
MAX_LABEL_WORDS = 12


class TrajectoryError(ValueError):
    """A trajectory file lacks something the replay needs; the message names the step."""


@dataclass(frozen=True)
class TaskPair:
    """One task's two runs and the public text around them."""

    task_id: str
    label: str
    plain_run: int  # the cap-50 confirm run that is replayed
    note: dict[str, str]  # what / resolved / check, each at most 12 words, from the lesson prompt


PAIRS = [
    TaskPair(
        "tobymao__sqlglot-1379",
        "Casting to an array of struct fails to parse in DuckDB",
        3,
        {
            "what": "DuckDB cast to a struct array, struct(...)[], failed to parse.",
            "resolved": "Let the array-suffix check in Parser._parse_types cover nested types.",
            "check": "python -m unittest tests.dialects.test_duckdb tests.test_parser",
        },
    ),
    TaskPair(
        "tobymao__sqlglot-2095",
        "Oracle query fails to parse when a column name contains #",
        2,
        {
            "what": "Oracle column names containing # failed to tokenize.",
            "resolved": "Add # to VAR_SINGLE_TOKENS on the Oracle tokenizer.",
            "check": "python -m unittest tests.dialects.test_oracle",
        },
    ),
    TaskPair(
        "tobymao__sqlglot-2529",
        "Snowflake staged-file reference raises list index out of range",
        2,
        {
            "what": "A trailing Snowflake @stage reference raised list index out of range.",
            "resolved": "Stop the @ name loop in _parse_table_parts when no token remains.",
            "check": "python -m unittest tests.dialects.test_snowflake",
        },
    ),
]


def _pair_up(
    messages: list[dict[str, Any]], label: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Each assistant message with its tool result (the final submit has none: model time only)."""
    pairs = []
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        step = len(pairs) + 1
        actions = message["extra"]["actions"]
        follower = messages[index + 1] if index + 1 < len(messages) else None
        if len(actions) != 1:
            raise TrajectoryError(f"{label} step {step}: {len(actions)} actions, expected 1")
        submits = SUBMIT_MARK in actions[0]["command"]
        if submits and (follower is None or follower["role"] != "tool"):
            follower = {
                "extra": {
                    "timestamp": message["extra"]["timestamp"],
                    "returncode": 0,
                    "raw_output": "",
                }
            }
        if follower is None or follower.get("role", "tool") != "tool":
            raise TrajectoryError(f"{label} step {step}: no tool result follows")
        pairs.append((message, follower))
    return pairs


def _step_cost(call: dict[str, Any], result: dict[str, Any], where: str) -> tuple[int, int, float]:
    try:
        usage = call["extra"]["response"]["usage"]
        timings = call["extra"]["response"]["timings"]
        model_s = (timings["prompt_ms"] + timings["predicted_ms"]) / 1000
        exec_s = max(0.0, result["extra"]["timestamp"] - call["extra"]["timestamp"])
        return usage["prompt_tokens"], usage["completion_tokens"], round(model_s + exec_s, 1)
    except KeyError as missing:
        raise TrajectoryError(f"{where}: trajectory lacks {missing}") from missing


def _outcome(command: str, result: str, *, failed: bool) -> str:
    if SUBMIT_MARK in command:
        return "solved" if result == SOLVED else "gave up"
    return "failed" if failed else "progress"


def steps_from_trajectory(
    trajectory: dict[str, Any], label: str, result: str
) -> list[dict[str, Any]]:
    """The replay steps of one run; raises TrajectoryError naming the step that cannot be read."""
    memory = RunMemory()
    steps = []
    for number, (call, reply) in enumerate(_pair_up(trajectory["messages"], label), start=1):
        command = call["extra"]["actions"][0]["command"]
        where = f"{label} step {number}"
        tokens_in, tokens_out, wall_s = _step_cost(call, reply, where)
        failed = failed_test_run(
            command, reply["extra"].get("raw_output", ""), reply["extra"]["returncode"]
        )
        tag = mistake_tag(command, memory, failed=failed)
        steps.append(
            {
                "step": number,
                "action": _bounded(action_label(command), where),
                "outcome": _outcome(command, result, failed=failed),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "wall_s": wall_s,
                "mistake_tag": tag,
                "wasted": tag == "repeated",
                "note": None,
                "classifier": None,
                "picker": None,
            }
        )
    return steps


def check_against_grader(steps: list[dict[str, Any]], grade: dict[str, Any], label: str) -> str:
    """The grader's result for the replayed run; raises when the trajectory disagrees with it."""
    submitted = steps[-1]["action"] == "Submit the patch"
    result = SOLVED if grade["resolved"] else NOT_SOLVED
    if len(steps) != grade["steps"]:
        raise TrajectoryError(
            f"{label}: {len(steps)} steps but the grader row says {grade['steps']}"
        )
    if submitted != grade["resolved"]:
        raise TrajectoryError(
            f"{label}: trajectory submitted={submitted}, grader resolved={grade['resolved']}"
        )
    return result


def _bounded(label: str, where: str) -> str:
    if len(label.split()) > MAX_LABEL_WORDS:
        raise TrajectoryError(f"{where}: label over {MAX_LABEL_WORDS} words: {label!r}")
    return label


def totals_of(steps: list[dict[str, Any]], result: str) -> dict[str, Any]:
    """Run totals computed from the steps, never typed."""

    def count(key: str, value: object) -> int:
        return sum(s[key] == value for s in steps)

    return {
        "steps": len(steps),
        "tokens_in": sum(s["tokens_in"] for s in steps),
        "tokens_out": sum(s["tokens_out"] for s in steps),
        "wall_s": round(sum(s["wall_s"] for s in steps), 1),
        "repeated_mistakes": count("mistake_tag", "repeated"),
        "new_mistakes": count("mistake_tag", "new"),
        "wasted_steps": count("wasted", True),
        "notes": sum(s["note"] is not None for s in steps),
        "result": result,
    }


def _record(rows: list[dict[str, Any]], shown: int) -> dict[str, int]:
    """The arm's full record on this task from the grader's rows, and which run is replayed."""
    return {
        "shown_run": shown,
        "runs_solved": sum(bool(r["resolved"]) for r in rows),
        "runs_total": len(rows),
    }


def _run_entry(
    run_id: str, label: str, subtitle: str, role: str, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": run_id,
        "label": label,
        "subtitle": subtitle,
        "role": role,
        "status": "measured",
        "model": "Glimmer",
        "adapter": None,
        "steps": steps,
    }


def _graded(
    run: dict[str, Any], rows: list[dict[str, Any]], shown: int, label: str
) -> dict[str, Any]:
    grade = next((r for r in rows if r["run"] == shown), None)
    if grade is None:
        raise TrajectoryError(f"{label}: no grader row for run {shown}")
    result = check_against_grader(run["steps"], grade, label)
    return {**run, **_record(rows, shown), "totals": totals_of(run["steps"], result)}


def build_replay(
    pair: TaskPair, plain: dict[str, Any], lesson: dict[str, Any], grades: dict[str, Any]
) -> dict[str, Any]:
    """One demo-replay-v1 document: the plain run, then the lesson-in-prompt run.

    `grades` is the task's rows from the calibration logs: {"plain": [...], "lesson": [...]}.
    """
    name = pair.task_id
    plain_steps = steps_from_trajectory(
        plain, f"{name} plain", result=grades_result(grades["plain"], pair.plain_run)
    )
    lesson_steps = steps_from_trajectory(
        lesson, f"{name} lesson", result=grades_result(grades["lesson"], 1)
    )
    lesson_steps[0]["note"] = {**pair.note, "source": LESSON_SOURCE}
    repo, number = name.replace("__", "/").rsplit("-", 1)
    plain_run = _graded(
        _run_entry("plain", "Plain Glimmer", PLAIN_SUBTITLE, "floor", plain_steps),
        grades["plain"],
        pair.plain_run,
        f"{name} plain",
    )
    lesson_run = _graded(
        _run_entry("personal", LESSON_LABEL, LESSON_SUBTITLE, "under test", lesson_steps),
        grades["lesson"],
        1,
        f"{name} lesson",
    )
    return {
        "schema": SCHEMA,
        "status": "measured",
        "source": SOURCE_LINE,
        "task": {"id": f"{repo.split('/')[1]}-{number}", "repo": repo, "label": pair.label},
        "runs": [plain_run, lesson_run],
    }


def grades_result(rows: list[dict[str, Any]], shown: int) -> str:
    """The grader's verdict for the replayed run (check_against_grader then compares the shape)."""
    row = next((r for r in rows if r["run"] == shown), None)
    if row is None:
        raise TrajectoryError(f"no grader row for run {shown}")
    return SOLVED if row["resolved"] else NOT_SOLVED


def write_replays(in_dir: Path, out_dir: Path) -> list[Path]:
    """Emit one `pilot-sqlglot-<n>.json` per task pair; returns the files written."""
    written = []
    for pair in PAIRS:
        number = pair.task_id.rsplit("-", 1)[1]
        plain = json.loads((in_dir / f"{number}-plain.json").read_text())
        lesson = json.loads((in_dir / f"{number}-lesson.json").read_text())
        grades = json.loads((in_dir / "grades.json").read_text())[number]
        target = out_dir / f"pilot-sqlglot-{number}.json"
        target.write_text(json.dumps(build_replay(pair, plain, lesson, grades), indent=1) + "\n")
        written.append(target)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    for path in write_replays(Path(argv[1]), Path(argv[2])):
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
