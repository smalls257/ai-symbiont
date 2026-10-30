"""PLUG-AGENT-2 replay: rebuild a recorded run's state at its first known mistake.

For Core's plain runs no container survives. The recorded commands are executed in order in a
scrubbed container; the erroring command must return the recorded code and the same normalized
error line, else the point is void. The rebuilt container is committed, as for own prefixes.
"""

import subprocess
from dataclasses import replace
from typing import Any

from plug_agent2_branch import FidelityError, image_tag, state_fingerprint
from plug_agent2_branchpoint import BranchPoint, find_branch_point
from plug_agent2_keys import RETURNCODE, Key, executed_actions, key_of
from plug_agent2_point import ReplayVoidError  # noqa: E402
from plug_agent_env import _environment
from plug_agent_notes import failure_of
from taskenv import TaskEnvError, history_scrub_script, install_script


class ReplayMismatchError(ReplayVoidError):
    """The replayed erroring command did not reproduce the recorded outcome: the point is void."""


def recorded_code(output: str) -> int | None:
    found = RETURNCODE.search(output)
    return int(found.group(1)) if found else None


def reproduces(point: BranchPoint, command: str, result: dict[str, Any]) -> bool:
    """The replayed result has the recorded return code and the same normalized error line."""
    failure = failure_of(command, result.get("returncode"), result.get("output", ""))
    recorded = recorded_code(point.messages[point.failing_observation]["content"])
    return (
        recorded == result.get("returncode")
        and failure is not None
        and key_of(failure) == point.key
    )


def replay_branch_point(
    row: dict, messages: list[dict], known: frozenset[Key]
) -> BranchPoint | None:
    """The branch point of a recorded run with its container rebuilt and committed; None when the
    run never makes a known mistake. Raises ReplayMismatchError or FidelityError (point void)."""
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
            result = env.execute({"command": step.command})
            if step.observation_index == point.failing_observation and not reproduces(
                point, step.command, result
            ):
                raise ReplayMismatchError(
                    "the erroring command did not reproduce its recorded outcome"
                )
        point = replace(point, fingerprint=state_fingerprint(env))
        subprocess.run(
            ["docker", "commit", env.container_id, image_tag(row["instance_id"])],
            check=True,
            capture_output=True,
        )
        return point
    finally:
        env.cleanup()


__all__ = ["FidelityError", "ReplayMismatchError", "replay_branch_point"]
