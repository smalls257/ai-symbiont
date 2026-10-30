"""One plain-Glimmer run on one sqlglot task with mini-SWE-agent (plan Task 22, Glimmer part).

Fresh container, history-free checkout, mini-SWE-agent's SWE-bench config talking to Glimmer, then
grading in another fresh container with FAIL_TO_PASS + PASS_TO_PASS. run_once never raises for a
task-level failure: the record's `error_kind` says infra, model_api, context or agent, and
`resolved` is None only when grading could not happen. staged.py decides which runs to do.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

import litellm
import yaml
from minisweagent.agents.default import DefaultAgent
from minisweagent.config import builtin_config_dir
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models.litellm_model import LitellmModel
from taskenv import TaskEnvError, grade, prepare_script

IMAGE = "swerebench/sweb.eval.x86_64.tobymao_1776_sqlglot-5015"  # shared image, see taskenv.py
MODEL = "openai/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
GLIMMER_URL_VAR = (
    "SYMBIONT_GLIMMER_URL"  # llama.cpp router, one request at a time; address is never committed
)
PREFLIGHT_TIMEOUT_S = 30  # one listing request; a server that cannot answer it cannot run a task
MAX_TOKENS = 4096  # per reply; bounds one step so the wall limit is checked often enough
# A stalled request must end in a recorded error: 2 tries x 600 s bounds a dead step to ~21 min
# (the 2026-10-28 hang was 10 x 1200 s); a healthy step takes 10-17 s.
REQUEST_TIMEOUT_S = 600
MODEL_RETRY_ATTEMPTS = 2
RETRY_ATTEMPTS_VAR = "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"  # read by mini-SWE-agent per query
API_ERRORS = (
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
)


@dataclass(frozen=True)
class Setting:
    reasoning: str  # Glimmer's "Reasoning strength: <x>" system line
    step_limit: int
    wall_limit_s: int
    adapter_id: int | None = None  # llama-server LoRA id applied at scale 1; None = plain Glimmer
    model: str = MODEL  # a router name of its own serves a personal Glimmer (the loop's rounds)
    teacher: str | None = None  # "spark" or "wonder": a remote teacher model through egress
    temperature: float | None = None  # None: the server's default (every run before Core D2)
    seed: int | None = None  # llama-server sampling seed; None: the server's default


def sampling(setting: Setting) -> dict:
    """The request's sampling fields; empty when the setting leaves the server's defaults."""
    found = {"temperature": setting.temperature, "seed": setting.seed}
    return {key: value for key, value in found.items() if value is not None}


def glimmer_url() -> str:
    url = os.environ.get(GLIMMER_URL_VAR)
    if not url:
        raise SystemExit(
            f"{GLIMMER_URL_VAR} is not set: export the Glimmer endpoint (see env.example)"
        )
    return url


def missing_on_server(listing: dict, model: str, adapter_id: int | None) -> str | None:
    """Why the router's /models `listing` cannot serve this run, in words; None when it can.

    An adapter run also needs the model's child launched with more than `adapter_id` --lora files.
    """
    served = {entry["id"]: entry for entry in listing.get("data", [])}
    if model not in served:
        return f"{model} is not listed by the Glimmer server (listed: {sorted(served)})"
    if adapter_id is None:
        return None
    status = served[model].get("status")
    args = status.get("args", []) if isinstance(status, dict) else []
    loras = sum(arg == "--lora" for arg in args)
    if loras <= adapter_id:
        return f"{model} has {loras} --lora adapter(s) loaded; adapter id {adapter_id} is absent"
    return None


def preflight(setting: Setting) -> None:
    """One /models request before any run; SystemExit naming a missing model or adapter."""
    root = glimmer_url().rstrip("/").removesuffix("/v1")
    listing_url = f"{root}/models"  # the configured Glimmer server only, never a typed host
    with urlopen(listing_url, timeout=PREFLIGHT_TIMEOUT_S) as response:  # noqa: S310  see above
        listing = json.loads(response.read())
    problem = missing_on_server(listing, setting.model.removeprefix("openai/"), setting.adapter_id)
    if problem:
        raise SystemExit(f"preflight failed, no run started: {problem}")


def bound_model_retries() -> None:
    """Cap mini-SWE-agent's per-query retries so a dead endpoint raises within minutes."""
    os.environ[RETRY_ATTEMPTS_VAR] = str(MODEL_RETRY_ATTEMPTS)


def agent_config(setting: Setting) -> tuple[dict, dict]:
    bound_model_retries()
    cfg = yaml.safe_load((builtin_config_dir / "benchmarks" / "swebench.yaml").read_text())
    agent = cfg["agent"] | {
        "step_limit": setting.step_limit,
        "wall_time_limit_seconds": setting.wall_limit_s,
        "cost_limit": 0,
    }
    agent["system_template"] = (
        f"Reasoning strength: {setting.reasoning}\n" + agent["system_template"]
    )
    if setting.teacher:  # the teacher's endpoint comes from egress, not from Glimmer's URL
        return agent, cfg["model"] | {
            "model_name": setting.teacher,
            "cost_tracking": "ignore_errors",
        }
    model = cfg["model"] | {
        "model_name": setting.model,
        "cost_tracking": "ignore_errors",  # local model: cost is 0 by construction
        "model_kwargs": {
            "api_base": glimmer_url(),
            "api_key": os.environ.get("SYMBIONT_GLIMMER_KEY", "none"),
            "timeout": REQUEST_TIMEOUT_S,
            "max_tokens": MAX_TOKENS,
            "drop_params": True,
            "parallel_tool_calls": True,
            **adapter_body(setting.adapter_id),
            **sampling(setting),
        },
    }
    return agent, model


def adapter_body(adapter_id: int | None) -> dict:
    """Request-body field that turns the served LoRA on for this run; nothing for plain Glimmer.

    llama-server applies `"lora": [{"id": N, "scale": 1}]` per request (the router forwards the
    body to the Glimmer child), so the personal arm and plain calibration share one server.
    """
    if adapter_id is None:
        return {}
    return {"extra_body": {"lora": [{"id": adapter_id, "scale": 1}]}}


def token_counts(messages: list[dict]) -> dict:
    prompt = completion = 0
    for message in messages:
        usage = ((message.get("extra") or {}).get("response") or {}).get("usage") or {}
        prompt += usage.get("prompt_tokens") or 0
        completion += usage.get("completion_tokens") or 0
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def classify(error: BaseException) -> str:
    if (
        isinstance(error, litellm.exceptions.ContextWindowExceededError)
        or "context" in str(error).lower()
    ):
        return "context"
    return "model_api" if isinstance(error, API_ERRORS) else "agent"


def _new_record(row: dict, run: int, setting: Setting, stage: str) -> dict:
    return {
        "instance_id": row["instance_id"],
        "stage": stage,
        "run": run,
        **asdict(setting),
        "image": IMAGE,
        "model": setting.model,
        "error_kind": None,
        "error": None,
        "started": time.time(),
    }


def _open_environment() -> DockerEnvironment:
    return DockerEnvironment(
        image=IMAGE,
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
    )  # no fetching the upstream fix


def _prepare_checkout(env: DockerEnvironment, row: dict) -> None:
    prep = env.execute({"command": prepare_script(row["base_commit"])}, timeout=900)
    if prep["returncode"] != 0:
        raise TaskEnvError(f"prepare failed rc={prep['returncode']}: {prep['output'][-800:]}")


def _run_agent(agent: DefaultAgent, row: dict, rec: dict) -> dict:
    try:
        return agent.run(row["problem_statement"])
    except Exception as error:  # noqa: BLE001  the agent already saved its exit message; record it
        rec["error_kind"] = classify(error)
        rec["error"] = f"{type(error).__name__}: {str(error)[-300:]}"
        return {"exit_status": type(error).__name__, "submission": ""}


def agent_model(setting: Setting, model_cfg: dict, rec: dict):
    """Plain or personal Glimmer, or a teacher run whose ledger run name is the task and run."""
    if not setting.teacher:
        return LitellmModel(**model_cfg)
    from teacher_model import Teacher, teacher_model  # only teacher runs need egress and the key

    label = f"teacher-{setting.teacher}-{rec['instance_id']}-run{rec['run']}"
    return teacher_model(Teacher(setting.teacher), label, model_cfg)


def _attempt(row: dict, setting: Setting, traj: Path, rec: dict, started: float) -> str | None:
    """Prepare the checkout, run the agent, record its outcome; return the submitted patch."""
    agent_cfg, model_cfg = agent_config(setting)
    env = None
    patch = None
    try:
        env = _open_environment()
        _prepare_checkout(env, row)
        rec["prepare_s"] = round(time.time() - started, 1)
        agent_started = time.time()
        agent = DefaultAgent(
            agent_model(setting, model_cfg, rec), env, output_path=traj, **agent_cfg
        )
        info = _run_agent(agent, row, rec)
        rec["agent_s"] = round(time.time() - agent_started, 1)
        rec["exit_status"] = info.get("exit_status")
        rec["steps"] = agent.n_calls
        rec |= token_counts(agent.messages)
        patch = info.get("submission") or ""
        rec["submitted"] = bool(patch.strip())
        rec["patch_lines"] = len(patch.splitlines())
    except Exception as error:  # noqa: BLE001  run_once never raises for a task-level failure
        rec["error_kind"], rec["error"] = "infra", f"{type(error).__name__}: {str(error)[-500:]}"
        rec["traceback_tail"] = traceback.format_exc()[-800:]
    finally:
        if env is not None:
            env.cleanup()
    return patch


def _grade_into(rec: dict, row: dict, patch: str) -> None:
    graded_started = time.time()
    try:
        graded = grade(IMAGE, row, patch, prepare=True)
        rec |= {
            "resolved": graded.resolved,
            "patch_applied": graded.patch_applied,
            "f2p": [graded.f2p_passed, graded.f2p_total],
            "p2p": [graded.p2p_passed, graded.p2p_total],
        }
    except TaskEnvError as error:
        rec["error_kind"] = "infra"
        rec["error"] = (rec["error"] or "") + f" | grade: {str(error)[-500:]}"
    rec["grade_s"] = round(time.time() - graded_started, 1)


def run_once(row: dict, run: int, setting: Setting, stage: str, traj_dir: Path) -> dict:
    rec = _new_record(row, run, setting, stage)
    started = time.time()
    traj = traj_dir / row["instance_id"] / f"{stage}-run{run}-{setting.reasoning}.traj.json"
    patch = _attempt(row, setting, traj, rec, started)
    if patch is not None and rec["error_kind"] != "model_api":
        _grade_into(rec, row, patch)
    rec.setdefault("resolved", None)  # None = not graded (see error); never counted as pass or fail
    rec["wall_s"] = round(time.time() - started, 1)
    return rec
