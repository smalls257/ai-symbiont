"""PLUG-AGENT-2 replay: rebuild a recorded run's container just before its first known mistake.

Recorded commands before the erroring turn run in order in a scrubbed container; each must return
its recorded code (a failed one also the same normalized error line), else the point is void. The
state hash is taken and the container committed; every branch checks the hash at start.
"""

import subprocess
from dataclasses import replace

from plug_agent2_branch import ReplayMismatchError, image_tag, state_fingerprint
from plug_agent2_branchpoint import BranchPoint, find_branch_point, matches_record
from plug_agent2_keys import Key, executed_actions
from plug_agent_env import _environment
from taskenv import TaskEnvError, history_scrub_script, install_script


def restore_branch_point(
    row: dict, messages: list[dict], known: frozenset[Key]
) -> BranchPoint | None:
    """The branch point of a recorded run with its pre-command container rebuilt and committed;
    None when the run never makes a known mistake. Raises ReplayMismatchError (point void)."""
    point = find_branch_point(messages, known)
    if point is None:
        return None
    env = _environment(row["docker_image"])
    try:
        if env.execute({"command": history_scrub_script()}, timeout=600)["returncode"] != 0:
            raise TaskEnvError("history scrub failed")
        install = install_script(row)
        if install:
            env.execute({"command": install}, timeout=600)
        for step in executed_actions(point.messages):
            if not matches_record(step, env.execute({"command": step.command})):
                raise ReplayMismatchError(
                    f"command {step.model_calls} did not reproduce its record"
                )
        point = replace(point, fingerprint=state_fingerprint(env))
        tag = image_tag(row["instance_id"])
        subprocess.run(["docker", "commit", env.container_id, tag], check=True, capture_output=True)
        return point
    finally:
        env.cleanup()
