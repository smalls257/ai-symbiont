"""PLUG-AGENT-2 per-task driver: a shared `none` prefix, then B branches for each note.

Notes at the branch point: nothing, and the forced lesson (the applies-labeled lesson with the
failing key). After it every arm is silent. The label file, label prompt and mistake rule must hash
to the config's pins; a branch lost twice or a changed restored state voids the point.
Usage: python plug_agent2_point.py ROWS TASK OUT CONFIG CONFIG_SHA256 LABELS STORES POOL
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
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


def checked_config(config_path: Path, expected_sha256: str, pinned: dict[str, Path]) -> dict:
    """The config, after its own hash and every pinned file the caller names match; the file
    pins in PINS are always required. `pinned` maps config fields (labels_sha256,
    pool_summary_sha256, selection_json_sha256, ...) to the files they pin."""
    if sha256_of(config_path) != expected_sha256:
        raise ConfigPinError("config file does not match the frozen hash")
    config = json.loads(config_path.read_text())
    for field, path in (pinned | PINS).items():
        if config.get(field) != sha256_of(path):
            raise ConfigPinError(f"{path.name} does not match config {field}")
    return config


def checked_server(models_listing: dict, config: dict) -> None:
    """The served model is the pinned GGUF: same alias, same byte size and parameter count (the
    file hash itself is checked where the file lives, at server start)."""
    served = models_listing["data"][0]
    meta = served.get("meta") or {}
    found = (served["id"], meta.get("size"), meta.get("n_params"))
    pinned = (config["model"], config["gguf_size_bytes"], config["gguf_n_params"])
    if found != pinned:
        raise ConfigPinError(f"served model {found[0]} differs from the pinned GGUF")


def served_models() -> dict:
    """The /models listing of the server named by SYMBIONT_GLIMMER_URL (bearer key from the
    environment, never printed)."""
    url = os.environ["SYMBIONT_GLIMMER_URL"].rstrip("/") + "/models"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    )
    with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 the configured server only
        return json.loads(reply.read())


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


class BranchLostError(RuntimeError):
    """A branch failed twice with an infra or model error."""


class PointVoidError(RuntimeError):
    """A primary branch was lost twice: the whole point is void and listed, with its arm."""

    def __init__(self, arm: str, index: int, reason: str) -> None:
        super().__init__(reason)
        self.arm, self.index = arm, index


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
    raise BranchLostError(last)


def run_branches(
    inputs: TaskInputs, point: BranchPoint, config: dict, traj_dir: Path
) -> list[dict]:
    """B branches for each distinct note: nothing, then the forced lesson."""
    silent = NoteSource(NoteArm.NONE, inputs.row["repo"], (), 0.0, 1.0)
    found = []
    for arm, text in (("none", None), ("forced", forced_note(inputs, point))):
        for index in range(config["branches_per_arm"]):
            traj = traj_dir / f"{arm}-{index}.traj.json"
            try:
                branch = graded_branch(inputs.row, point, Continuation(text, silent), config, traj)
            except BranchLostError as error:
                raise PointVoidError(arm, index, str(error)) from error
            found.append({"arm": arm, "index": index} | branch)
    return found


def main() -> None:
    rows_path, task, out, config_path, expected, labels_path, stores_path, pool_path = sys.argv[1:9]
    pinned = {"labels_sha256": Path(labels_path), "pool_summary_sha256": Path(pool_path)}
    config = checked_config(Path(config_path), expected, pinned)
    checked_server(served_models(), config)
    row = {r["instance_id"]: r for r in json.loads(Path(rows_path).read_text())}[task]
    inputs = TaskInputs(
        row,
        json.loads(Path(labels_path).read_text())["labels"][task],
        json.loads(Path(stores_path).read_text())[task]["lessons"],
    )
    traj_dir = Path(out) / "traj" / task
    traj_dir.mkdir(parents=True, exist_ok=True)
    record: dict = {"instance_id": task, "branches": []}
    known = known_keys(inputs.labels, inputs.lessons)
    try:
        point, record["prefix"] = run_prefix(row, known, config, traj_dir / "prefix.traj.json")
        if point is not None:
            record["branches"] = run_branches(inputs, point, config, traj_dir)
    except PointVoidError as error:
        record["void"] = {"arm": error.arm, "index": error.index, "reason": str(error)}
    except FidelityError as error:
        record["void"] = {"arm": None, "index": None, "reason": f"fidelity: {error}"}
    finally:
        for image in (image_tag(task), row["docker_image"]):
            subprocess.run(["docker", "rmi", image], capture_output=True, check=False)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
