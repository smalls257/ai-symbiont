"""One PLUG-AGENT-1 run: mini-SWE-agent in the task's SWE-rebench image, notes per arm.

The environment wrapper follows `mini_swe_wrapper`: after a failed command the arm's note is
appended to that command's observation under the `[symbiont]` tag line. Every failed command is
keyed the same way in every arm, so repeated known mistakes count alike. Logs ids and counts,
never prompt or note text.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calibration"))

from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.environments.docker import DockerEnvironment  # noqa: E402
from plug_agent_notes import JudgeDownError, NoteSource, failure_of, known_mistake  # noqa: E402
from run_calibration import Setting, agent_config, agent_model, classify, token_counts  # noqa: E402
from taskenv import TaskEnvError, grade, history_scrub_script, install_script  # noqa: E402
from teacher_model import Teacher, teacher_model  # noqa: E402

from symbiont.delivery.mini_swe_wrapper import tagged  # noqa: E402


@dataclass
class RunLog:
    """What one run's commands did: failure keys, known mistakes, notes shown."""

    failure_keys: list[list[str]] = field(default_factory=list)
    known_mistakes: int = 0
    steps: int = 0


class LocalNotedEnvironment:
    """The inner environment; after a failed command, the arm's note on its observation."""

    def __init__(self, inner: Any, source: NoteSource, log: RunLog) -> None:
        self._inner, self._source, self._log = inner, source, log

    def __getattr__(self, name: str) -> Any:
        if name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)

    def serialize(self) -> dict[str, Any]:
        """The inner record plus the arm name."""
        record: dict[str, Any] = self._inner.serialize()
        info = record.get("info", {})
        config = {**info.get("config", {}), "symbiont_wrap": {"arm": str(self._source.arm)}}
        return {**record, "info": {**info, "config": config}}

    def execute(self, action: dict[str, Any], cwd: str = "", *, timeout: int | None = None):
        """Run the command; on a failure, count it and append the arm's note."""
        result: dict[str, Any] = self._inner.execute(action, cwd, timeout=timeout)
        self._log.steps += 1
        failure = failure_of(
            str(action.get("command", "")), result.get("returncode"), result.get("output", "")
        )
        if failure is None:
            return result
        self._log.failure_keys.append(list(failure.key()))
        self._log.known_mistakes += known_mistake(failure, self._source.store)
        note = self._source.note_for(self._log.steps, failure)
        if note:
            result = result | {"output": f"{result.get('output', '')}\n{tagged(note)}"}
        return result


def _environment(image: str) -> DockerEnvironment:
    return DockerEnvironment(
        image=image,
        cwd="/testbed",
        timeout=60,
        env={"PAGER": "cat", "MANPAGER": "cat", "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1"},
        interpreter=["bash", "-c"],
        run_args=["--rm", "--network", "none"],
    )


def run_task(row: dict, source: NoteSource, config: dict, traj: Path) -> dict:
    """One graded run; one record whatever happened (resolved None = not graded)."""
    rec: dict[str, Any] = {"instance_id": row["instance_id"], "arm": str(source.arm)}
    log, started = RunLog(), time.time()
    try:
        patch, fields = _agent_run(row, source, config, traj, log)
    except JudgeDownError:
        raise  # stops the whole run (plug_agent_run), never a void record
    except Exception as error:  # noqa: BLE001  a container that never started: void, re-queued
        patch, fields = (
            "",
            {"error_kind": "infra", "error": f"{type(error).__name__}: {str(error)[-200:]}"},
        )
    rec |= fields
    void = rec["error_kind"] in (
        "model_api",
        "infra",
    )  # not the agent's doing: re-queued, not scored
    rec |= {"resolved": None} if void else _graded(row, patch)
    rec |= {"wall_s": round(time.time() - started, 1), "submitted": bool(patch.strip())}
    return rec | {"failure_keys": log.failure_keys, "known_mistakes": log.known_mistakes,
                  "notes": source.events}  # fmt: skip


def _agent_run(
    row: dict, source: NoteSource, config: dict, traj: Path, log: RunLog
) -> tuple[str, dict]:
    """Run the agent; the submitted patch and the record's error, exit, steps and tokens."""
    rec: dict[str, Any] = {"error_kind": None}
    env = None
    try:
        env = _environment(row["docker_image"])
        scrubbed = env.execute({"command": history_scrub_script()}, timeout=600)
        if scrubbed["returncode"] != 0:  # a future commit would show the agent the gold fix
            raise TaskEnvError(f"history scrub failed rc={scrubbed['returncode']}")
        install = install_script(row)
        if install:  # the agent works in the same installed checkout the grader tests
            env.execute({"command": install}, timeout=600)
        model, agent_cfg = _model(row, source, config)
        wrapped = LocalNotedEnvironment(env, source, log)
        agent = DefaultAgent(model, wrapped, output_path=traj, **agent_cfg)
        info = _agent_exit(agent, row, rec)
        rec |= {"exit_status": info.get("exit_status"), "agent_steps": agent.n_calls}
        rec |= token_counts(agent.messages)
        return info.get("submission") or "", rec
    finally:
        if env is not None:
            env.cleanup()


def _model(row: dict, source: NoteSource, config: dict) -> tuple[Any, dict]:
    """The agent's model and loop settings: plain Glimmer (the default), or Spark through egress."""
    teacher = "spark" if config["agent"] == "spark" else None
    named = (
        {"model": config["model"]} if config.get("model") else {}
    )  # Core D2: a router name per arm
    setting = Setting(
        "low", config["step_limit"], config["wall_limit_min"] * 60, teacher=teacher,
        temperature=config["temperature"], seed=config.get("seed"), **named,
    )  # fmt: skip
    agent_cfg, model_cfg = agent_config(setting)
    if (
        teacher is None
    ):  # Glimmer on the owner's own server: temperature and seed ride in the request
        return agent_model(setting, model_cfg, {}), agent_cfg
    label = f"{config['run_label']}-{row['instance_id']}-{source.arm}"
    model = teacher_model(Teacher.SPARK, label, model_cfg, temperature=config["temperature"],
                          reply_tokens=config["max_tokens_per_reply"])  # fmt: skip
    return model, agent_cfg


def _agent_exit(agent: DefaultAgent, row: dict, rec: dict) -> dict:
    """The agent's exit info; an exception is recorded with its kind, never a silent pass."""
    try:
        return agent.run(row["problem_statement"])
    except JudgeDownError:
        raise  # fail closed: a judge arm with no judge is a none run under the judge's name
    except Exception as error:  # noqa: BLE001  recorded with its kind
        rec |= {
            "error_kind": classify(error),
            "error": f"{type(error).__name__}: {str(error)[-200:]}",
        }
        return {"exit_status": type(error).__name__, "submission": ""}


def _graded(row: dict, patch: str) -> dict:
    """The official grade; a grader error leaves resolved None and says so."""
    try:
        return {"resolved": grade(row["docker_image"], row, patch, prepare=False).resolved}
    except TaskEnvError as error:
        return {"resolved": None, "grade_error": str(error)[-200:]}
