"""One Glimmer run on one Django task with mini-SWE-agent, in the task's own SWE-bench image.

Same harness as the sqlglot calibration; the image is per task (history scrubbed) and grading
is swev_env.grade. Each arm reads only its own endpoint variables, so the personal arm can never
run on plain Glimmer. run_once returns one record per run and never raises for a task failure.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calibration"))

from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.config import builtin_config_dir  # noqa: E402
from minisweagent.environments.docker import DockerEnvironment  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel  # noqa: E402
from run_calibration import MODEL, Setting, classify, token_counts  # noqa: E402
from swev_env import ScorerError, grade, scrub_history_script  # noqa: E402

MAX_TOKENS = 4096  # per reply, as in the calibration runner
# CAL2's bound on a dead endpoint: 2 attempts x 600 s, never an hours-long hang.
REQUEST_TIMEOUT_S = 600
MODEL_RETRY_ATTEMPTS = "2"
RETRY_ATTEMPTS_VAR = "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"


class Arm(StrEnum):
    """Plain Glimmer (floor) or personal Glimmer: same base plus the Django LoRA (under test)."""

    PLAIN = "plain"
    PERSONAL = "personal"


@dataclass(frozen=True)
class Slot:
    """Which run this is: phase ("pilot", "history", "later"), arm and run number."""

    phase: str
    arm: Arm
    run: int


# (url variable, model-name variable or None for the calibration's fixed model name)
ENDPOINT_VARS = {
    Arm.PLAIN: ("SYMBIONT_GLIMMER_URL", None),
    Arm.PERSONAL: ("SYMBIONT_PERSONAL_GLIMMER_URL", "SYMBIONT_PERSONAL_GLIMMER_MODEL"),
}


def required_env(name: str) -> str:
    """The variable's value; SystemExit naming it when unset (addresses are never committed)."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set: export it (see env.example)")
    return value


def endpoint(arm: Arm) -> tuple[str, str]:
    """(model name, api base) of an arm, from its own variables only."""
    url_var, model_var = ENDPOINT_VARS[arm]
    model = required_env(model_var) if model_var else MODEL
    return model, required_env(url_var)


def agent_config(setting: Setting, arm: Arm) -> tuple[dict, dict]:
    """The calibration's agent and model config, pointed at the arm's endpoint."""
    os.environ[RETRY_ATTEMPTS_VAR] = MODEL_RETRY_ATTEMPTS
    model_name, api_base = endpoint(arm)
    cfg = yaml.safe_load((builtin_config_dir / "benchmarks" / "swebench.yaml").read_text())
    agent = cfg["agent"] | {
        "step_limit": setting.step_limit,
        "wall_time_limit_seconds": setting.wall_limit_s,
        "cost_limit": 0,
    }
    agent["system_template"] = (
        f"Reasoning strength: {setting.reasoning}\n" + (agent["system_template"])
    )
    model = cfg["model"] | {
        "model_name": model_name,
        "cost_tracking": "ignore_errors",  # local model: cost is 0 by construction
        "model_kwargs": {
            "api_base": api_base,
            "api_key": "none",
            "timeout": REQUEST_TIMEOUT_S,
            "max_tokens": MAX_TOKENS,
            "drop_params": True,
            "parallel_tool_calls": True,
        },
    }
    return agent, model


def open_environment(image: str) -> DockerEnvironment:
    """The agent's container: the task image, no network, the calibration's env."""
    return DockerEnvironment(
        image=image,
        cwd="/testbed",
        timeout=60,
        env={
            "PAGER": "cat",
            "MANPAGER": "cat",
            "PIP_PROGRESS_BAR": "off",
            "TQDM_DISABLE": "1",
            "BASH_ENV": "/root/.bashrc",
        },
        interpreter=["bash", "-c"],
        run_args=["--rm", "--network", "none"],
    )


def scrub(env: DockerEnvironment) -> None:
    """Remove future history from /testbed; raises ScorerError if any stays."""
    done = env.execute({"command": scrub_history_script()}, timeout=900)
    if done["returncode"] != 0:
        raise ScorerError(f"history scrub failed rc={done['returncode']}: {done['output'][-600:]}")


def run_agent(agent: DefaultAgent, row: dict, rec: dict) -> dict:
    """The agent's exit info; an exception inside the agent is recorded with its kind."""
    try:
        return agent.run(row["problem_statement"])
    except Exception as error:  # noqa: BLE001  the agent saved its exit message; record the kind
        rec["error_kind"] = classify(error)
        rec["error"] = f"{type(error).__name__}: {str(error)[-300:]}"
        return {"exit_status": type(error).__name__, "submission": ""}


def attempt(row: dict, arm: Arm, setting: Setting, traj: Path, rec: dict) -> str | None:
    """Scrub, run the agent, record its outcome; the submitted patch, None if it never ran."""
    agent_cfg, model_cfg = agent_config(setting, arm)
    env, patch, started = None, None, time.time()
    try:
        env = open_environment(row["image"])
        scrub(env)
        rec["prepare_s"] = round(time.time() - started, 1)
        agent = DefaultAgent(LitellmModel(**model_cfg), env, output_path=traj, **agent_cfg)
        info = run_agent(agent, row, rec)
        rec["agent_s"] = round(time.time() - started - rec["prepare_s"], 1)
        rec |= {"exit_status": info.get("exit_status"), "steps": agent.n_calls}
        rec |= token_counts(agent.messages)
        patch = info.get("submission") or ""
        rec |= {"submitted": bool(patch.strip()), "patch_lines": len(patch.splitlines())}
    except Exception as error:  # noqa: BLE001  run_once never raises for a task-level failure
        rec["error_kind"], rec["error"] = "infra", f"{type(error).__name__}: {str(error)[-500:]}"
        rec["traceback_tail"] = traceback.format_exc()[-800:]
    finally:
        if env is not None:
            env.cleanup()
    return patch


def grade_into(rec: dict, row: dict, patch: str) -> None:
    """Official grade into the record; a scorer failure leaves resolved None and says why."""
    started = time.time()
    try:
        found = grade(row, patch)
        rec |= {"resolved": found.resolved, "outcome": str(found.outcome)}
        rec |= {"f2p": list(found.f2p), "p2p": list(found.p2p)}
    except ScorerError as error:
        rec["error_kind"] = "infra"
        rec["error"] = (rec["error"] or "") + f" | grade: {str(error)[-500:]}"
    rec["grade_s"] = round(time.time() - started, 1)


def run_once(row: dict, slot: Slot, setting: Setting, traj_dir: Path) -> dict:
    """One run, graded; one record whatever happened (see the module docstring)."""
    iid, arm = row["instance_id"], slot.arm
    rec = {"instance_id": iid, "phase": slot.phase, "arm": str(arm), "run": slot.run}
    rec |= asdict(setting) | {"model": endpoint(arm)[0], "image": row["image"]}
    rec |= {"error_kind": None, "error": None}
    started = rec["started"] = time.time()
    name = f"{slot.phase}-{arm}-run{slot.run}-cap{setting.step_limit}.traj.json"
    patch = attempt(row, arm, setting, traj_dir / iid / name, rec)
    if patch is not None and rec["error_kind"] != "model_api":
        grade_into(rec, row, patch)
    rec.setdefault("resolved", None)  # None = not graded (see error); never a pass or a fail
    rec["wall_s"] = round(time.time() - started, 1)
    return rec
