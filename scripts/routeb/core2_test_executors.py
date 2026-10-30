"""Core D2 test executors: one run of one arm on one server, by repository family.

SWE-rebench repositories (sqlglot and the four new ones) run through the Plug harness; Django
(SWE-bench Verified images) runs through the Django driver's `run_once`. Both scrub the container
to the base commit's history first; a failed scrub is an infra (void) record. A name missing from
the server's config raises: an arm never runs as plain under another arm's name.
Arm W is plain Glimmer with worked examples prepended to the issue (core2_worked_examples).
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from core2_test_plan import TEMPERATURE, Arm, Executor, RunSpec
from core2_worked_examples import example_block, most_similar

STEP_LIMIT = 75  # prereg "Arms": step cap 75
WALL_LIMIT_MIN = 45  # prereg "Arms": wall cap 45 min
DJANGO = "django/django"
PROBE_TIMEOUT_S = 10
KEY_VARIABLE = "SYMBIONT_GLIMMER_KEY"  # Bearer key of a server that needs one; never logged


def arm_model(server: dict, arm: Arm) -> str:
    """The router model name serving the arm on this server; W uses the plain model."""
    return server["models"]["P" if arm is Arm.W else str(arm)]


def load_key(server: dict) -> None:
    """Put the server's Bearer key (from its key file) into the environment for the harness."""
    if server.get("key_file"):
        os.environ[KEY_VARIABLE] = Path(server["key_file"]).expanduser().read_text().strip()
    else:
        os.environ.pop(KEY_VARIABLE, None)


def server_probe(server: dict) -> bool:
    """True when the server answers its health endpoint; False on any network or HTTP failure."""
    root = server["url"].rstrip("/").removesuffix("/v1")
    request = urllib.request.Request(f"{root}/health")  # noqa: S310  the configured server only
    if os.environ.get(KEY_VARIABLE):
        request.add_header("Authorization", f"Bearer {os.environ[KEY_VARIABLE]}")
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as reply:  # noqa: S310
            return reply.status == 200
    except (urllib.error.URLError, OSError):
        return False


def with_examples(row: dict, server: dict) -> dict:
    """The row with the two most similar earlier solved tasks prepended to its issue (arm W)."""
    config = server["examples"]
    earlier = [r for r in json.loads(Path(config["rows"]).read_text()) if r["repo"] == row["repo"]]
    solved = Path(config["trajectories"])
    earlier = [r for r in earlier if (solved / f"{r['instance_id']}.traj.json").is_file()]
    picked = most_similar(row["problem_statement"], earlier)
    shown = [
        (r, json.loads((solved / f"{r['instance_id']}.traj.json").read_text())["messages"])
        for r in picked
    ]
    return row | {"problem_statement": example_block(shown) + row["problem_statement"]}


def rebench_executor(row: dict, server: dict, out: Path, spec: RunSpec) -> dict:
    """One SWE-rebench run through the Plug harness with the arm's model and seed."""
    from plug_agent_env import run_task  # noqa: PLC0415
    from plug_agent_notes import NoteArm, NoteSource  # noqa: PLC0415

    settings = {"agent": "glimmer", "step_limit": STEP_LIMIT, "wall_limit_min": WALL_LIMIT_MIN,
                "temperature": TEMPERATURE, "seed": spec.seed, "model": arm_model(server, spec.arm),
                "max_tokens_per_reply": 4096, "run_label": "core2-d2"}  # fmt: skip
    traj = out / "traj" / row["instance_id"] / f"{spec.arm}-run{spec.run}.traj.json"
    return run_task(row, NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0), settings, traj)


def django_executor(row: dict, server: dict, out: Path, spec: RunSpec) -> dict:
    """One Django run through the Django driver; adapters are served under the personal name."""
    from run_calibration import Setting  # noqa: PLC0415
    from swev_run import Arm as DjangoArm  # noqa: PLC0415
    from swev_run import Slot, run_once  # noqa: PLC0415

    model = arm_model(server, spec.arm)
    setting = Setting(
        "low", STEP_LIMIT, WALL_LIMIT_MIN * 60, temperature=TEMPERATURE, seed=spec.seed, model=model
    )
    kind = DjangoArm.PLAIN if spec.arm in (Arm.P, Arm.W) else DjangoArm.PERSONAL
    os.environ["SYMBIONT_PERSONAL_GLIMMER_MODEL"] = model
    os.environ["SYMBIONT_PERSONAL_GLIMMER_URL"] = os.environ["SYMBIONT_GLIMMER_URL"]
    return run_once(row, Slot("later", kind, spec.run), setting, out / "traj")


def build_executor(server: dict, rows_path: Path, out: Path) -> Executor:
    """The executor one runner process calls; picks the family by the task's repository."""
    load_key(server)
    rows = {r["instance_id"]: r for r in json.loads(rows_path.read_text())}

    def execute(spec: RunSpec) -> dict:
        row = rows[spec.task]
        if spec.arm is Arm.W:
            row = with_examples(row, server)
        family = django_executor if row.get("repo", DJANGO) == DJANGO else rebench_executor
        return family(row, server, out, spec)

    return execute
