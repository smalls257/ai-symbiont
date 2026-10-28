"""Turn real mini-SWE-agent trajectories of the lesson-in-prompt pilot into demo-replay-v1 files.

Every number is read from a trajectory (usage, timings, return codes), totals are summed from the
steps, and an unreadable step raises TrajectoryError. Tag heuristics: dashboard/AGENTS.md.

    uv run python scripts/routea/build_pilot_replay.py IN_DIR OUT_DIR
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "demo-replay-v1"
SOURCE_LINE = (
    "real runs, one per arm: plain hit the 50-step cap; "
    "lesson in prompt (pilot), not the LoRA; no classifier"
)
SOLVED = "solved"
NOT_SOLVED = "not solved"
LESSON_SOURCE = "lesson in prompt (pilot)"
SUBMIT_MARK = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MAX_LABEL_WORDS = 12


class TrajectoryError(ValueError):
    """A trajectory file lacks something the replay needs; the message names the step."""


@dataclass(frozen=True)
class TaskPair:
    """One task's two runs and the public text around them."""

    task_id: str
    label: str
    note: dict[str, str]  # what / resolved / check, each at most 12 words, from the lesson prompt


PAIRS = [
    TaskPair(
        "tobymao__sqlglot-1379",
        "Casting to an array of struct fails to parse in DuckDB",
        {
            "what": "DuckDB cast to a struct array, struct(...)[], failed to parse.",
            "resolved": "Let the array-suffix check in Parser._parse_types cover nested types.",
            "check": "python -m unittest tests.dialects.test_duckdb tests.test_parser",
        },
    ),
    TaskPair(
        "tobymao__sqlglot-2095",
        "Oracle query fails to parse when a column name contains #",
        {
            "what": "Oracle column names containing # failed to tokenize.",
            "resolved": "Add # to VAR_SINGLE_TOKENS on the Oracle tokenizer.",
            "check": "python -m unittest tests.dialects.test_oracle",
        },
    ),
    TaskPair(
        "tobymao__sqlglot-2529",
        "Snowflake staged-file reference raises list index out of range",
        {
            "what": "A trailing Snowflake @stage reference raised list index out of range.",
            "resolved": "Stop the @ name loop in _parse_table_parts when no token remains.",
            "check": "python -m unittest tests.dialects.test_snowflake",
        },
    ),
]

TEST_RUN = re.compile(r"(?:unittest|pytest)\s+(.*)")
SOURCE_PATH = re.compile(r"(?:/testbed/)?((?:sqlglot|tests)/[\w/]+\.py)")
SED_RANGE = re.compile(r"sed -n '(\d+),(\d+)p'\s+(\S+)")
SCRIPT_FILE = re.compile(r"(?:python3?|cat >)\s+(\S+\.py)")


@dataclass
class RunMemory:
    """What this run has already read and which commands already failed."""

    reads: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    failed: set[str] = field(default_factory=set)


def _repo_path(command: str) -> str | None:
    found = SOURCE_PATH.search(command)
    return found.group(1) if found else None


def _test_target(command: str) -> str:
    tail = TEST_RUN.search(command)
    first = tail.group(1).split()[0] if tail else ""
    return first.replace(".", "/") + ".py" if first.startswith("tests.") else first


def _is_write(command: str) -> bool:
    return bool(
        re.search(r"sed -i|write_text|open\([^)]*['\"]w['\"]\)|\.write\(|writelines", command)
    )


def action_label(command: str) -> str:
    """A short public label for one shell command, shaped by what the step did."""
    path = _repo_path(command)
    if SUBMIT_MARK in command:
        return "Submit the patch"
    if "git diff" in command or "patch.txt" in command:
        return "Write out the patch" if "git diff" in command else "Review the patch"
    if TEST_RUN.search(command) and "python -m" in command:
        return f"Run {_test_target(command)}"
    if _is_write(command) and path and path.startswith("sqlglot/"):
        return f"Edit {path}"
    if re.search(r"cat > |<< ?'?\w+'?", command):
        return "Write a scratch script"
    return _read_or_search_label(command, path)


def _read_or_search_label(command: str, path: str | None) -> str:
    ranged = SED_RANGE.search(command)
    if ranged:
        low, high, target = ranged.groups()
        return f"Read {_repo_path(target) or target} lines {low}-{high}"
    if re.match(r"(cd \S+ && )?(cat|head|tail|awk)\b", command) and path:
        return f"Read {path}"
    if "grep" in command:
        return f"Search {path}" if path else "Search the code"
    if re.match(r"(cd \S+ && )?(ls|find)\b", command):
        return "List the repository files"
    if "git log" in command:
        return "Check the git history"
    return _run_label(command)


def _run_label(command: str) -> str:
    script = SCRIPT_FILE.search(command)
    if script:
        name = script.group(1).split("/")[-1]
        return "Run the reproduction" if "reproduce" in name else "Run a scratch script"
    if "python" in command and " -c " in command:
        return "Check the example query"
    if command.startswith("cp "):
        return "Back up a file"
    if "pip install" in command:
        return "Install the package"
    return "Run a shell command"


def _failed_test_run(command: str, output: str, returncode: int) -> bool:
    if returncode != 0:
        return True
    ran_tests = bool(TEST_RUN.search(command)) and "python -m" in command
    return ran_tests and bool(re.search(r"^(FAILED|ERROR)|\nFAILED|\nERROR:|Traceback", output))


def _overlaps(low: int, high: int, seen: list[tuple[int, int]]) -> bool:
    return any(low <= end and start <= high for start, end in seen)


def _is_reread(command: str, memory: RunMemory) -> bool:
    ranged = SED_RANGE.search(command)
    if ranged:
        target = ranged.group(3).removeprefix("/testbed/")
        low, high = int(ranged.group(1)), int(ranged.group(2))
        again = _overlaps(low, high, memory.reads.get(target, []))
        memory.reads.setdefault(target, []).append((low, high))
        return again
    whole = re.match(r"(?:cd \S+ && )?cat\s+(\S+\.py)\s*$", command)
    if not whole:
        return False
    target = whole.group(1).removeprefix("/testbed/")
    again = target in memory.reads
    memory.reads.setdefault(target, []).append((0, 10**9))
    return again


def mistake_tag(command: str, memory: RunMemory, *, failed: bool) -> str:
    """repeated / new / none under the heuristics in the module docstring."""
    reread = _is_reread(command, memory)
    rerun = failed and command in memory.failed
    if failed:
        memory.failed.add(command)
    if reread or rerun:
        return "repeated"
    return "new" if failed else "none"


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
        failed = _failed_test_run(
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


def _bounded(label: str, where: str) -> str:
    if len(label.split()) > MAX_LABEL_WORDS:
        raise TrajectoryError(f"{where}: label over {MAX_LABEL_WORDS} words: {label!r}")
    return label


def totals_of(steps: list[dict[str, Any]], result: str) -> dict[str, Any]:
    """Run totals computed from the steps, never typed."""
    count = lambda key, value: sum(s[key] == value for s in steps)  # noqa: E731
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


def _run_entry(
    run_id: str, label: str, role: str, steps: list[dict[str, Any]], result: str
) -> dict[str, Any]:
    return {
        "id": run_id,
        "label": label,
        "role": role,
        "status": "measured",
        "model": "Glimmer",
        "adapter": None,
        "steps": steps,
        "totals": totals_of(steps, result),
    }


def build_replay(pair: TaskPair, plain: dict[str, Any], lesson: dict[str, Any]) -> dict[str, Any]:
    """One demo-replay-v1 document: the plain run, then the lesson-in-prompt run."""
    plain_steps = steps_from_trajectory(plain, f"{pair.task_id} plain", result=NOT_SOLVED)
    lesson_steps = steps_from_trajectory(lesson, f"{pair.task_id} lesson", result=SOLVED)
    lesson_steps[0]["note"] = {**pair.note, "source": LESSON_SOURCE}
    repo, number = pair.task_id.replace("__", "/").rsplit("-", 1)
    return {
        "schema": SCHEMA,
        "status": "measured",
        "source": SOURCE_LINE,
        "task": {"id": f"{repo.split('/')[1]}-{number}", "repo": repo, "label": pair.label},
        "runs": [
            _run_entry("plain", "Plain Glimmer", "floor", plain_steps, result=NOT_SOLVED),
            _run_entry(
                "personal",
                "Glimmer with a lesson in the prompt (pilot)",
                "under test",
                lesson_steps,
                result=SOLVED,
            ),
        ],
    }


def write_replays(in_dir: Path, out_dir: Path) -> list[Path]:
    """Emit one `pilot-sqlglot-<n>.json` per task pair; returns the files written."""
    written = []
    for pair in PAIRS:
        number = pair.task_id.rsplit("-", 1)[1]
        plain = json.loads((in_dir / f"{number}-plain.json").read_text())
        lesson = json.loads((in_dir / f"{number}-lesson.json").read_text())
        target = out_dir / f"pilot-sqlglot-{number}.json"
        target.write_text(json.dumps(build_replay(pair, plain, lesson), indent=1) + "\n")
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
