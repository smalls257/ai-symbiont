"""PLUG-AGENT-2 branch points: where a run first makes a known mistake, and how an arm resumes.

Every arm must face the same state, so the branch point is read from the shared prefix's message
history alone: the first executed command whose failure key is a known mistake. An arm resumes from
the history up to that command's observation, with its note appended to that observation, and the
primary indicator asks whether the same key fails again afterwards. Pure.
"""

import copy
from collections.abc import Sequence
from dataclasses import dataclass

from plug_agent2_keys import RETURNCODE, Key, executed_actions, failures_in, key_of
from plug_agent_notes import Failure, failure_of

from symbiont.delivery.mini_swe_wrapper import tagged


@dataclass(frozen=True)
class BranchPoint:
    """The shared state at the first known mistake."""

    messages: tuple[dict, ...]  # up to and including every observation of the failing step
    model_calls: int
    failing_observation: int  # index of the failing command's observation message
    failure: Failure
    key: Key


def find_branch_point(messages: Sequence[dict], known: frozenset[Key]) -> BranchPoint | None:
    """The first executed command that fails with a known key, once its whole step is in the
    history; None before that."""
    for step in executed_actions(messages):
        code = RETURNCODE.search(step.output)
        failure = failure_of(step.command, int(code.group(1)) if code else None, step.output)
        key = key_of(failure) if failure else None
        if failure is None or key not in known:
            continue
        end = step.observation_index + (step.action_count - step.action_index)
        if end > len(messages):
            return None
        return BranchPoint(
            tuple(copy.deepcopy(list(messages[:end]))), step.model_calls,
            step.observation_index, failure, key,
        )  # fmt: skip
    return None


def resume_messages(point: BranchPoint, note: str | None) -> list[dict]:
    """A fresh copy of the shared history with the arm's note under the failing observation."""
    messages = copy.deepcopy(list(point.messages))
    if note:
        failing = messages[point.failing_observation]
        failing["content"] = f"{failing['content']}\n{tagged(note)}"
    return messages


def repeated_after(messages: Sequence[dict], point: BranchPoint) -> bool:
    """The branch point's key fails again in the steps after the shared history."""
    later = failures_in(messages[len(point.messages) :])
    return any(failure is not None and key_of(failure) == point.key for failure in later)
