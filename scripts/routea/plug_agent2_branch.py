"""PLUG-AGENT-2 branch execution: one shared prefix, then every arm continues from the same state.

The prefix runs the `none` arm in the task's scrubbed image until its first known mistake
(`find_branch_point` on the message history), then stops, commits the container to a local image
and keeps the history. Each arm starts a container from that image with the history replayed, its
note under the failing observation, and W further model calls. Heavy imports (mini-SWE-agent,
Docker) live here; the decisions are in plug_agent2_branchpoint.py. Logs ids and counts only.
"""

import copy
import subprocess
import time
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import FormatError, InterruptAgentFlow
from plug_agent2_branchpoint import BranchPoint, find_branch_point, repeated_after, resume_messages
from plug_agent2_keys import Key
from plug_agent_env import LocalNotedEnvironment, RunLog, _agent_exit, _environment, _model
from plug_agent_notes import NoteArm, NoteSource
from taskenv import TaskEnvError, history_scrub_script, install_script

WINDOW = 15  # further model calls after the branch point (prereg: W)
MAX_FORMAT_ERRORS = 3


class PrefixAgent(DefaultAgent):
    """Stops itself with an exit message once its history holds a known mistake."""

    def __init__(self, *args: Any, known: frozenset[Key], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.known, self.point = known, None

    def step(self) -> list[dict]:
        added = super().step()
        self.point = find_branch_point(self.messages, self.known)
        if self.point is not None:
            exit_extra = {"exit_status": "BranchPoint", "submission": ""}
            self.add_messages({"role": "exit", "content": "BranchPoint", "extra": exit_extra})
        return added


class ResumedAgent(DefaultAgent):
    """Continues a given history instead of starting from the task statement."""

    def run_from(self, messages: list[dict], model_calls: int) -> dict:
        """Step until an exit message; the step limit is the window's end."""
        self.messages, self.n_calls, errors = messages, model_calls, 0
        while self.messages[-1].get("role") != "exit":
            try:
                self.step()
                errors = 0
            except FormatError as error:
                errors += 1
                self.add_messages(*error.messages)
                if errors >= MAX_FORMAT_ERRORS:
                    extra = {"exit_status": "RepeatedFormatError", "submission": ""}
                    self.add_messages(
                        {"role": "exit", "content": "RepeatedFormatError", "extra": extra}
                    )
            except InterruptAgentFlow as error:
                self.add_messages(*error.messages)
            except Exception as error:
                self.handle_uncaught_exception(error)
                raise
            finally:
                self.save(self.config.output_path)
        return self.messages[-1].get("extra", {})


def image_tag(task: str) -> str:
    """The local image holding the task's shared prefix state."""
    return "plug2-branch:" + task.lower().replace("__", "-").replace("_", "-")


def run_prefix(
    row: dict, known: frozenset[Key], config: dict, traj: Path
) -> tuple[BranchPoint | None, dict]:
    """Run the `none` prefix; (branch point or None, record). The container state is committed to
    `image_tag` when a branch point is reached."""
    record: dict[str, Any] = {"instance_id": row["instance_id"], "error_kind": None}
    env = _environment(row["docker_image"])
    try:
        scrubbed = env.execute({"command": history_scrub_script()}, timeout=600)
        if scrubbed["returncode"] != 0:
            raise TaskEnvError(f"history scrub failed rc={scrubbed['returncode']}")
        install = install_script(row)
        if install:
            env.execute({"command": install}, timeout=600)
        source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
        model, agent_cfg = _model(row, source, config)
        agent = PrefixAgent(
            model,
            LocalNotedEnvironment(env, source, RunLog()),
            known=known,
            output_path=traj,
            **agent_cfg,
        )
        _agent_exit(agent, row, record)
        if agent.point is not None:
            subprocess.run(
                ["docker", "commit", env.container_id, image_tag(row["instance_id"])],
                check=True,
                capture_output=True,
            )
        return agent.point, record | {"model_calls": agent.n_calls}
    finally:
        env.cleanup()


def run_continuation(
    row: dict, point: BranchPoint, source: NoteSource, config: dict, traj: Path
) -> dict:
    """One arm from the branch point: its note for the failure, then WINDOW model calls; whether
    the key repeats."""
    note = source.note_for(point.model_calls, point.failure)
    started = time.time()
    env = _environment(image_tag(row["instance_id"]))
    try:
        model, agent_cfg = _model(row, source, config)
        agent_cfg = copy.deepcopy(agent_cfg) | {"step_limit": point.model_calls + WINDOW}
        agent = ResumedAgent(
            model, LocalNotedEnvironment(env, source, RunLog()), output_path=traj, **agent_cfg
        )
        extra = agent.run_from(resume_messages(point, note), point.model_calls)
        return {
            "arm": str(source.arm),
            "note_shown": bool(note),
            "repeated": repeated_after(agent.messages, point),
            "exit_status": extra.get("exit_status"),
            "calls_after": agent.n_calls - point.model_calls,
            "wall_s": round(time.time() - started, 1),
            "notes": source.events,
        }
    finally:
        env.cleanup()
