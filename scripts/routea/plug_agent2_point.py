"""PLUG-AGENT-2 per-task driver: a shared `none` prefix, then B branches for each note.

Notes at the branch point: nothing, and the forced lesson (the applies-labeled lesson with the
failing key). After it every arm is silent. The label file, label prompt and mistake rule must hash
to the config's pins; a branch lost twice or a changed restored state voids the point.
Usage: plug_agent2_point.py ROWS TASK OUT CONFIG SHA256 LABELS STORES POOL [RUN ORDINAL SOURCE]
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from plug_agent2_branch import (
    Continuation,
    FidelityError,
    ReplayMismatchError,
    TaskEnvError,
    image_tag,
    run_continuation,
    run_prefix,
)
from plug_agent2_branchpoint import BranchPoint
from plug_agent2_errorline import is_generic_environment
from plug_agent2_measure import known_keys, lesson_key
from plug_agent_notes import NoteArm, NoteSource

HERE = Path(__file__).resolve().parent
PINS = {
    "label_prompt_sha256": HERE / "plug_agent2_label_prompt.md",
    "mistake_rule_sha256": HERE / "plug_agent2_keys.py",
    "error_line_rule_sha256": HERE / "plug_agent2_errorline.py",
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


PROBE_BRANCHES = 3  # the stop-rule probe: none arm only, 3 branches per point, never scored


def run_branches(
    inputs: TaskInputs, point: BranchPoint, config: dict, traj_dir: Path
) -> list[dict]:
    """B branches for each note, interleaved by index (none, forced, none, forced, ...) so a drift
    of the server over the point's hours falls on both arms. The probe runs `none` only."""
    silent = NoteSource(NoteArm.NONE, inputs.row["repo"], (), 0.0, 1.0)
    probing = os.environ.get("PLUG2_PROBE") == "1"
    arms = [("none", None)] if probing else [("none", None), ("forced", forced_note(inputs, point))]
    found = []
    for index in range(PROBE_BRANCHES if probing else config["branches_per_arm"]):
        for arm, text in arms:
            traj = traj_dir / f"{arm}-{index}.traj.json"
            try:
                branch = graded_branch(inputs.row, point, Continuation(text, silent), config, traj)
            except BranchLostError as error:
                raise PointVoidError(arm, index, str(error)) from error
            found.append(branch | {"arm": arm, "index": index})
    return found


def prefix_point(
    row: dict, known: frozenset, config: dict, traj_dir: Path, recorded: str | None
) -> tuple:
    """(branch point or None, prefix record): an own prefix run or a recorded Core run, either way
    rebuilt by replay to the state just before the first known mistake."""
    from plug_agent2_replay import restore_branch_point  # noqa: PLC0415  heavy imports only here

    if recorded is None:
        messages, record = run_prefix(row, known, config, traj_dir / "prefix.traj.json")
        source = record | {"source": "own"}
    else:
        messages = json.loads(Path(recorded[0]).read_text())["messages"]
        source = {
            "source": "core-replay",
            "trajectory": Path(recorded[0]).name,
            "ordinal": recorded[1],
        }
    ordinal = recorded[1] if recorded else 0
    return (restore_branch_point(row, messages, known, ordinal) if messages else None), source


VOID_ERRORS = (FidelityError, ReplayMismatchError, TaskEnvError, subprocess.CalledProcessError)


def checked_inputs(argv: list[str]) -> tuple[TaskInputs, dict, tuple[str, int] | None, str]:
    """(task inputs, checked config, recorded run and ordinal or None, task id) from the command
    line; raises before anything runs if a pin, the server or an input is wrong."""
    rows_path, task, _, config_path, expected, labels_path, stores_path, pool_path = argv[:8]
    recorded = (argv[8], int(argv[9]) if len(argv) > 9 else 0) if len(argv) > 8 else None
    source_name = argv[10] if len(argv) > 10 else ("core" if recorded else "own")
    prefix = "core_" if source_name == "core" else ""
    pinned = {
        f"{prefix}labels_sha256": Path(labels_path),
        f"{prefix}pool_summary_sha256": Path(pool_path),
    }
    config = checked_config(Path(config_path), expected, pinned)
    checked_server(served_models(), config)
    row = {r["instance_id"]: r for r in json.loads(Path(rows_path).read_text())}[task]
    labels = json.loads(Path(labels_path).read_text())["labels"][task]
    lessons = json.loads(Path(stores_path).read_text())[task]["lessons"]
    return TaskInputs(row, labels, lessons), config, recorded, task


def main() -> None:
    inputs, config, recorded, task = checked_inputs(sys.argv[1:])
    traj_dir = Path(sys.argv[3]) / "traj" / task
    traj_dir.mkdir(parents=True, exist_ok=True)
    record: dict = {"instance_id": task, "branches": []}
    try:
        known = known_keys(inputs.labels, inputs.lessons)
        point, record["prefix"] = prefix_point(inputs.row, known, config, traj_dir, recorded)
        if point is not None:
            record["point"] = {"generic_environment": is_generic_environment(point.key[0])}
            record["branches"] = run_branches(inputs, point, config, traj_dir)
    except PointVoidError as error:
        record["void"] = {"arm": error.arm, "index": error.index, "reason": str(error)}
    except LookupError as error:  # no applies lesson carries the key: listed, never a crash
        record["void"] = {"arm": None, "index": None, "reason": f"LookupError: {error}"}
    except VOID_ERRORS as error:
        record["void"] = {"arm": None, "index": None, "reason": f"{type(error).__name__}: {error}"}
    finally:
        for image in (image_tag(task), inputs.row["docker_image"]):
            subprocess.run(["docker", "rmi", image], capture_output=True, check=False)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
