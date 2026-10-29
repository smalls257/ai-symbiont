"""Turn real personal Glimmer (sqlglot LoRA adapter) trajectories into demo-replay-v1 files.

A personal replay is shown only when the adapter really ran (adapter_id 0, no lesson in the prompt)
and the plain run beside it failed; the result comes from the grader row, never the trajectory.

    uv run python scripts/routea/build_personal_replay.py IN_DIR OUT_DIR TASK_NUMBER [...]

IN_DIR: `<n>-plain.json`, `<n>-personal.json`, `plain-rows.jsonl`, `personal-rows.jsonl`."""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_pilot_replay import (  # noqa: E402  (the sibling module is found through the path line above)
    NOT_SOLVED,
    SCHEMA,
    SOLVED,
    TrajectoryError,
    check_against_grader,
    steps_from_trajectory,
    totals_of,
)

PLAIN_SUBTITLE = "Glimmer, no adapter, no notes"
PERSONAL_LABEL = "Personal Glimmer (LoRA adapter, sqlglot)"
PERSONAL_SUBTITLE = "sqlglot LoRA adapter, no lesson in the prompt, no notes"
ADAPTER_NAME = "sqlglot LoRA adapter"
SOURCE_LINE = (
    "real runs: plain Glimmer failed; personal Glimmer (sqlglot LoRA adapter, "
    "no lesson in the prompt) under test"
)
PERSONAL_ARM = "personal_lora"
ADAPTER_ID = 0  # the single sqlglot adapter the eval launcher loads (--adapter 0)
PLAIN_STAGE = "confirm"  # pilot ruling: the screen run solved by selection, so it is left out

LABELS = {
    "1379": "Casting to an array of struct fails to parse in DuckDB",
    "1944": "Spark DATEDIFF to DuckDB prints the unit as None",
    "2095": "Oracle query fails to parse when a column name contains #",
    "2529": "Snowflake staged-file reference raises list index out of range",
    "2658": "A Windows line break leaves whitespace in token text",
}


def _rows(path: Path, number: str) -> list[dict[str, Any]]:
    suffix = f"-{number}"
    lines = path.read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return [row for row in rows if row["instance_id"].endswith(suffix)]


def plain_rows(path: Path, number: str) -> list[dict[str, Any]]:
    """The reused confirm runs of one task; raises when there are none."""
    rows = [r for r in _rows(path, number) if r["stage"] == PLAIN_STAGE]
    if not rows:
        raise TrajectoryError(f"sqlglot-{number}: no {PLAIN_STAGE} rows in {path.name}")
    return rows


def personal_rows(path: Path, number: str) -> list[dict[str, Any]]:
    """The adapter runs of one task; raises on a row that is not a no-lesson adapter run."""
    rows = _rows(path, number)
    if not rows:
        raise TrajectoryError(f"sqlglot-{number}: no adapter rows in {path.name}")
    for row in rows:
        if row.get("adapter_id") != ADAPTER_ID or row.get("arm") != PERSONAL_ARM:
            raise TrajectoryError(f"sqlglot-{number} run {row['run']}: not an adapter run")
        if row.get("lesson_sha") is not None:
            raise TrajectoryError(f"sqlglot-{number} run {row['run']}: a lesson was in the prompt")
    return rows


def _run_number(row: dict[str, Any]) -> int:
    return row["run"]


def first_failed(rows: list[dict[str, Any]], number: str) -> dict[str, Any]:
    """The earliest failed plain run, the one shown beside the adapter run."""
    failed = sorted((r for r in rows if not r["resolved"]), key=_run_number)
    if not failed:
        raise TrajectoryError(f"sqlglot-{number}: no failed plain run to pair with")
    return failed[0]


def _run(run_id: str, label: str, subtitle: str, adapter: str | None, rows: list[dict]):
    """A run entry; the role follows from the adapter: no adapter is the floor."""
    return {
        "id": run_id,
        "label": label,
        "subtitle": subtitle,
        "role": "under test" if adapter else "floor",
        "status": "measured",
        "model": "Glimmer",
        "adapter": adapter,
        "rows": rows,
    }


def _finish(entry: dict[str, Any], steps: list[dict[str, Any]], shown: dict[str, Any], name: str):
    rows = entry.pop("rows")
    result = check_against_grader(steps, shown, f"{name} {entry['id']}")
    record = {
        "shown_run": shown["run"],
        "runs_solved": sum(bool(r["resolved"]) for r in rows),
        "runs_total": len(rows),
    }
    return {**entry, **record, "steps": steps, "totals": totals_of(steps, result)}


def build_replay(
    number: str,
    plain_traj: dict[str, Any],
    personal_traj: dict[str, Any],
    plain_graded: list[dict[str, Any]],
    personal_graded: list[dict[str, Any]],
) -> dict[str, Any]:
    """One demo-replay-v1 document: a failed plain run, then the solved personal run."""
    name = f"sqlglot-{number}"
    plain_shown = first_failed(plain_graded, number)
    personal_shown = next((r for r in personal_graded if r["resolved"]), None)
    if personal_shown is None:
        raise TrajectoryError(f"{name}: personal Glimmer did not solve it; nothing to show")
    plain_steps = steps_from_trajectory(plain_traj, f"{name} plain", NOT_SOLVED)
    personal_steps = steps_from_trajectory(personal_traj, f"{name} personal", SOLVED)
    plain = _run("plain", "Plain Glimmer", PLAIN_SUBTITLE, None, plain_graded)
    personal = _run("personal", PERSONAL_LABEL, PERSONAL_SUBTITLE, ADAPTER_NAME, personal_graded)
    return {
        "schema": SCHEMA,
        "status": "measured",
        "source": SOURCE_LINE,
        "task": {"id": name, "repo": "tobymao/sqlglot", "label": LABELS[number]},
        "runs": [
            _finish(plain, plain_steps, plain_shown, name),
            _finish(personal, personal_steps, personal_shown, name),
        ],
    }


def write_replay(in_dir: Path, out_dir: Path, number: str) -> Path:
    """Emit `personal-sqlglot-<number>.json`; raises TrajectoryError when the pair is not honest."""
    plain_graded = plain_rows(in_dir / "plain-rows.jsonl", number)
    personal_graded = personal_rows(in_dir / "personal-rows.jsonl", number)
    plain = json.loads((in_dir / f"{number}-plain.json").read_text())
    personal = json.loads((in_dir / f"{number}-personal.json").read_text())
    doc = build_replay(number, plain, personal, plain_graded, personal_graded)
    target = out_dir / f"personal-sqlglot-{number}.json"
    target.write_text(json.dumps(doc, indent=1) + "\n")
    return target


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    for number in argv[3:]:
        print(f"wrote {write_replay(Path(argv[1]), Path(argv[2]), number).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
