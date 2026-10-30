"""Core D2 test executors: one run of one arm, by repository family. Needs docker and Glimmer.

SWE-rebench repositories (sqlglot and the four new ones) run through the Plug harness; Django
(SWE-bench Verified images) runs through the Django driver's `run_once`. Both scrub the container
to the base commit's history first and report a failed scrub as an infra (void) record. A name
missing from the config raises; an arm is never run as plain under another arm's name.
"""

import json
import os
from pathlib import Path

from core2_test_plan import TEMPERATURE, Arm, Executor, RunSpec

STEP_LIMIT = 75  # prereg "Arms": step cap 75
WALL_LIMIT_MIN = 45  # prereg "Arms": wall cap 45 min
DJANGO = "django/django"


def arm_model(config: dict, arm: Arm) -> str:
    """The router model name serving the arm; KeyError names an unconfigured arm."""
    if arm is Arm.W:
        raise NotImplementedError("W (worked examples) has no executor yet")
    return config["models"][str(arm)]


def rebench_executor(row: dict, config: dict, out: Path, spec: RunSpec) -> dict:
    """One SWE-rebench run through the Plug harness with the arm's model and seed."""
    from plug_agent_env import run_task  # noqa: PLC0415
    from plug_agent_notes import NoteArm, NoteSource  # noqa: PLC0415

    settings = {"agent": "glimmer", "step_limit": STEP_LIMIT, "wall_limit_min": WALL_LIMIT_MIN,
                "temperature": TEMPERATURE, "seed": spec.seed, "model": arm_model(config, spec.arm),
                "max_tokens_per_reply": 4096, "run_label": "core2-d2"}  # fmt: skip
    traj = out / "traj" / row["instance_id"] / f"{spec.arm}-run{spec.run}.traj.json"
    return run_task(row, NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0), settings, traj)


def django_executor(row: dict, config: dict, out: Path, spec: RunSpec) -> dict:
    """One Django run through the Django driver; adapters are served under the personal name."""
    from run_calibration import Setting  # noqa: PLC0415
    from swev_run import Arm as DjangoArm  # noqa: PLC0415
    from swev_run import Slot, run_once  # noqa: PLC0415

    model = arm_model(config, spec.arm)
    setting = Setting(
        "low", STEP_LIMIT, WALL_LIMIT_MIN * 60, temperature=TEMPERATURE, seed=spec.seed, model=model
    )
    kind = DjangoArm.PLAIN if spec.arm is Arm.P else DjangoArm.PERSONAL
    os.environ["SYMBIONT_PERSONAL_GLIMMER_MODEL"] = model
    os.environ.setdefault("SYMBIONT_PERSONAL_GLIMMER_URL", os.environ["SYMBIONT_GLIMMER_URL"])
    return run_once(row, Slot("later", kind, spec.run), setting, out / "traj")


def build_executor(config: dict, rows_path: Path, out: Path) -> Executor:
    """The executor the runner calls; picks the family by the task's repository."""
    rows = {r["instance_id"]: r for r in json.loads(rows_path.read_text())}

    def execute(spec: RunSpec) -> dict:
        row = rows[spec.task]
        family = django_executor if row.get("repo", DJANGO) == DJANGO else rebench_executor
        return family(row, config, out, spec)

    return execute
