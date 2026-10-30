"""PLUG-AGENT-2 branch execution: a shared `none` prefix, then every arm continues from one state.

The prefix runs until its first known mistake and stops; the state just before that command is
rebuilt by replay (plug_agent2_replay.py) and committed. Each arm starts a container from that
image with the history replayed (the forced arm's note under its last message) and W further model
calls. Heavy imports live here; the decisions are in plug_agent2_branchpoint.py.
"""

import copy
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import FormatError, InterruptAgentFlow
from plug_agent2_branchpoint import (
    BranchPoint,
    find_branch_point,
    program_failed_after,
    repeated_after,
    replacement_errors,
    resume_messages,
    steps_lost,
)
from plug_agent2_keys import Key
from plug_agent_env import LocalNotedEnvironment, RunLog, _agent_exit, _environment, _model
from plug_agent_notes import NoteArm, NoteSource
from taskenv import TaskEnvError, history_scrub_script, install_script

FINGERPRINT_SCRIPT = (
    "cd /testbed && { git diff HEAD | sha256sum; git status --porcelain | sha256sum; "
    "git ls-files -o --exclude-standard -z | sort -z | xargs -0 -r sha256sum | sha256sum; }"
)
WINDOW = 15  # further model calls after the branch point (prereg: W)
MAX_FORMAT_ERRORS = 3


class FidelityError(RuntimeError):
    """A restored container's state hash differs from the prefix's: the point is void."""


class ReplayMismatchError(RuntimeError):
    """A replayed command did not reproduce its recorded outcome: the point is void."""


def state_fingerprint(env: Any) -> str:
    """Hash of the working tree's diff, status and untracked files inside the container."""
    result = env.execute({"command": FINGERPRINT_SCRIPT}, timeout=300)
    if result["returncode"] != 0:
        raise FidelityError(f"fingerprint failed rc={result['returncode']}")
    return result["output"].strip()


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
) -> tuple[list | None, dict]:
    """Run the `none` prefix until its first known mistake; (the run's messages, or None when it
    never makes one, and the record). The branch state is rebuilt by replay, not kept."""
    record: dict[str, Any] = {"instance_id": row["instance_id"], "error_kind": None}
    env = _environment(row["docker_image"])
    try:
        scrubbed = env.execute({"command": history_scrub_script()}, timeout=600)
        if scrubbed["returncode"] != 0:
            raise TaskEnvError(f"history scrub failed rc={scrubbed['returncode']}")
        install = install_script(row)
        if install and env.execute({"command": install}, timeout=600)["returncode"] != 0:
            raise TaskEnvError("package install failed in the prefix container")
        source = NoteSource(NoteArm.NONE, row["repo"], (), 0.0, 1.0)
        model, agent_cfg = _model(row, source, config)
        wrapped = LocalNotedEnvironment(env, source, RunLog())
        agent = PrefixAgent(model, wrapped, known=known, output_path=traj, **agent_cfg)
        _agent_exit(agent, row, record)
        messages = copy.deepcopy(agent.messages) if agent.point is not None else None
        return messages, record | {"model_calls": agent.n_calls}
    finally:
        env.cleanup()


@dataclass(frozen=True)
class Continuation:
    """One branch: the note under the failing observation (None: nothing) and the silent source
    that keeps later failures keyed the same way in every arm."""

    note: str | None
    source: NoteSource


def run_continuation(
    row: dict, point: BranchPoint, plan: Continuation, config: dict, traj: Path
) -> dict:
    """One branch from the branch point: its note, then WINDOW model calls; whether the key
    repeats."""
    source, note = plan.source, plan.note
    started = time.time()
    env = _environment(image_tag(row["instance_id"]))
    try:
        if state_fingerprint(env) != point.fingerprint:
            raise FidelityError("restored container differs from the prefix state")
        model, agent_cfg = _model(row, source, config)
        agent_cfg = copy.deepcopy(agent_cfg) | {"step_limit": point.model_calls + WINDOW}
        agent = ResumedAgent(
            model, LocalNotedEnvironment(env, source, RunLog()), output_path=traj, **agent_cfg
        )
        extra = agent.run_from(resume_messages(point, note), point.model_calls)
        return {
            "arm": str(source.arm),
            "note_shown": bool(note),
            "repeated": repeated_after(agent.messages, point, WINDOW),
            "same_program_failed": program_failed_after(agent.messages, point, WINDOW),
            "replacement_errors": replacement_errors(agent.messages, point, WINDOW),
            "steps_lost": steps_lost(agent.messages, point, WINDOW),
            "exit_status": extra.get("exit_status"),
            "calls_after": agent.n_calls - point.model_calls,
            "wall_s": round(time.time() - started, 1),
            "notes": source.events,
        }
    finally:
        env.cleanup()
