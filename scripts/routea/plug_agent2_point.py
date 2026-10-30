"""PLUG-AGENT-2 per-task driver: a shared `none` prefix, then B branches for each note.

Notes at the branch point: nothing, and the forced lesson (the applies-labeled lesson with the
failing key). After it every arm is silent. The label file, label prompt and mistake rule must hash
to the config's pins; a branch lost twice or a changed restored state voids the point.
Usage: python plug_agent2_point.py ROWS TASK OUT CONFIG LABELS STORES
"""

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from plug_agent2_branch import Continuation, FidelityError, image_tag, run_continuation, run_prefix
from plug_agent2_branchpoint import BranchPoint
from plug_agent2_measure import known_keys, lesson_key
from plug_agent_notes import NoteArm, NoteSource

HERE = Path(__file__).resolve().parent
PINS = {
    "label_prompt_sha256": HERE / "plug_agent2_label_prompt.md",
    "mistake_rule_sha256": HERE / "plug_agent2_keys.py",
}


class ConfigPinError(RuntimeError):
    """A pinned file does not hash to the config's value; nothing was run."""


@dataclass(frozen=True)
class TaskInputs:
    row: dict
    labels: dict[str, str]
    lessons: list[dict]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_config(config_path: Path, labels_path: Path) -> dict:
    """The config, after the label file, the label prompt and the key rule match their pins."""
    config = json.loads(config_path.read_text())
    for field, path in ({"labels_sha256": labels_path} | PINS).items():
        if config.get(field) != sha256_of(path):
            raise ConfigPinError(f"{path.name} does not match config {field}")
    return config


def lesson_text(lesson: dict) -> str:
    return (
        f"In {lesson['repo']}, `{lesson['failed']}` failed with {lesson['error']}; "
        f"run `{lesson['fix']}` instead."
    )


def forced_note(inputs: TaskInputs, point: BranchPoint) -> str:
    """The applies-labeled lesson note with the failing key (lowest id); LookupError if none."""
    matches = sorted(
        (
            x
            for x in inputs.lessons
            if inputs.labels.get(x["lesson_id"]) == "applies" and lesson_key(x) == point.key
        ),
        key=lambda lesson: lesson["lesson_id"],
    )
    if not matches:
        raise LookupError(f"no applies lesson has key {point.key}")
    return lesson_text(matches[0])


class PointVoidError(RuntimeError):
    """A primary branch was lost twice: the whole point is void and listed."""


def graded_branch(
    row: dict, point: BranchPoint, plan: Continuation, config: dict, traj: Path
) -> dict:
    """One branch, requeued once on an error; a second loss voids the point (a fidelity
    mismatch is never requeued)."""
    for _attempt in (1, 2):
        try:
            return run_continuation(row, point, plan, config, traj)
        except FidelityError:
            raise
        except Exception as error:  # noqa: BLE001  recorded by kind, then the point is void
            last = f"{type(error).__name__}: {str(error)[-120:]}"
    raise PointVoidError(last)


def run_branches(
    inputs: TaskInputs, point: BranchPoint, config: dict, traj_dir: Path
) -> list[dict]:
    """B branches for each distinct note: nothing, then the forced lesson."""
    silent = NoteSource(NoteArm.NONE, inputs.row["repo"], (), 0.0, 1.0)
    found = []
    for arm, text in (("none", None), ("forced", forced_note(inputs, point))):
        for index in range(config["branches_per_arm"]):
            traj = traj_dir / f"{arm}-{index}.traj.json"
            branch = graded_branch(inputs.row, point, Continuation(text, silent), config, traj)
            found.append({"arm": arm, "index": index} | branch)
    return found


def main() -> None:
    rows_path, task, out, config_path, labels_path, stores_path = sys.argv[1:7]
    config = checked_config(Path(config_path), Path(labels_path))
    row = {r["instance_id"]: r for r in json.loads(Path(rows_path).read_text())}[task]
    inputs = TaskInputs(
        row,
        json.loads(Path(labels_path).read_text())["labels"][task],
        json.loads(Path(stores_path).read_text())[task]["lessons"],
    )
    traj_dir = Path(out) / "traj" / task
    traj_dir.mkdir(parents=True, exist_ok=True)
    record: dict = {"instance_id": task, "branches": []}
    try:
        point, record["prefix"] = run_prefix(
            row, known_keys(inputs.labels, inputs.lessons), config, traj_dir / "prefix.traj.json"
        )
        if point is not None:
            record["branches"] = run_branches(inputs, point, config, traj_dir)
    except (FidelityError, PointVoidError) as error:
        record["void"] = f"{type(error).__name__}: {error}"
    finally:
        for image in (image_tag(task), row["docker_image"]):
            subprocess.run(["docker", "rmi", image], capture_output=True, check=False)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
