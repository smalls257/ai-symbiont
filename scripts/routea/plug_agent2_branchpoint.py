"""PLUG-AGENT-2 branch points: where a run first makes a known mistake, and how an arm resumes.

Every arm must face the same state, so the branch point is read from the shared run's message
history alone: the first executed command whose failure key is a known mistake. The arms resume
from the history up to, and excluding, the assistant turn that issued that command, in a container
holding the effects of everything before it. The forced arm sees the note at that point; the
outcome is whether the same normalized error line occurs again within W calls. Pure.
"""

import copy
from collections.abc import Sequence
from dataclasses import dataclass

from plug_agent2_keys import RETURNCODE, Executed, Key, executed_actions, key_of
from plug_agent_notes import Failure, failure_of

from symbiont.delivery.mini_swe_wrapper import tagged
from symbiont.miner.commands import normalise_command


@dataclass(frozen=True)
class BranchPoint:
    """The shared state just before the first known mistake."""

    messages: tuple[dict, ...]  # everything before the assistant turn that issued the command
    model_calls: int  # assistant turns in `messages`
    failure: Failure  # the recorded failure of the command the turn issued
    key: Key
    fingerprint: str = ""  # the rebuilt container's state hash, set when it is committed


def find_branch_point(messages: Sequence[dict], known: frozenset[Key]) -> BranchPoint | None:
    """The first executed command that fails with a known key, once its whole step is in the
    history; the point holds the history before the turn that issued it. None before that."""
    for step in executed_actions(messages):
        code = RETURNCODE.search(step.output)
        failure = failure_of(step.command, int(code.group(1)) if code else None, step.output)
        key = key_of(failure) if failure else None
        if failure is None or key not in known:
            continue
        end = step.observation_index + (step.action_count - step.action_index)
        if end > len(messages):
            return None
        turn = step.observation_index - step.action_index - 1  # index of the issuing assistant turn
        return BranchPoint(
            tuple(copy.deepcopy(list(messages[:turn]))), step.model_calls - 1, failure, key
        )
    return None


def resume_messages(point: BranchPoint, note: str | None) -> list[dict]:
    """A fresh copy of the shared history; the forced arm's note is appended under its last
    message, so the agent has it in view before it chooses its next command."""
    messages = copy.deepcopy(list(point.messages))
    if note:
        last = messages[-1]
        if not isinstance(last["content"], str):
            raise TypeError("the last message of the history has no text content to carry the note")
        last["content"] = f"{last['content']}\n{tagged(note)}"
    return messages


def occurrences_after(
    messages: Sequence[dict], point: BranchPoint, window: int | None = None
) -> int:
    """How many times the point's normalized error line occurs in the branch, within `window`
    further model calls when given (the prereg's W)."""
    found = 0
    for step in executed_actions(messages[len(point.messages) :]):
        if window is not None and step.model_calls > window:
            break
        code = RETURNCODE.search(step.output)
        failure = failure_of(step.command, int(code.group(1)) if code else None, step.output)
        found += failure is not None and key_of(failure) == point.key
    return found


def repeated_after(messages: Sequence[dict], point: BranchPoint, window: int | None = None) -> bool:
    """The same normalized error line occurs in the branch (the primary outcome)."""
    return occurrences_after(messages, point, window) > 0


def failures_after(
    messages: Sequence[dict], point: BranchPoint, window: int | None = None
) -> list[tuple[str, Failure]]:
    """(program, failure) of every failed command in the branch within `window` model calls."""
    found = []
    for step in executed_actions(messages[len(point.messages) :]):
        if window is not None and step.model_calls > window:
            break
        code = RETURNCODE.search(step.output)
        failure = failure_of(step.command, int(code.group(1)) if code else None, step.output)
        if failure is not None:
            found.append((normalise_command(step.command)[0], failure))
    return found


def program_failed_after(
    messages: Sequence[dict], point: BranchPoint, window: int | None = None
) -> bool:
    """The point's program fails with ANY error in the branch (the co-primary: a note that only
    swaps one error for another does not count as prevention)."""
    return any(
        program == point.failure.program for program, _ in failures_after(messages, point, window)
    )


def replacement_errors(
    messages: Sequence[dict], point: BranchPoint, window: int | None = None
) -> int:
    """Failures of the point's program in the branch whose error line differs from the point's."""
    return sum(
        program == point.failure.program and key_of(failure) != point.key
        for program, failure in failures_after(messages, point, window)
    )


def _outcome(step: Executed, point: BranchPoint) -> str:
    """ "error" if the step shows the point's error line, "fixed" if the point's program ran
    successfully, else "other"."""
    code = RETURNCODE.search(step.output)
    returncode = int(code.group(1)) if code else None
    failure = failure_of(step.command, returncode, step.output)
    if failure is not None and key_of(failure) == point.key:
        return "error"
    ran_well = returncode == 0 and normalise_command(step.command)[0] == point.failure.program
    return "fixed" if ran_well else "other"


def steps_lost(messages: Sequence[dict], point: BranchPoint, window: int | None = None) -> int:
    """Model calls from the first occurrence of the error in the branch to the next successful run
    of the same program, or to the branch's end (or `window`); 0 if the error never occurs."""
    steps = executed_actions(messages[len(point.messages) :])
    steps = [step for step in steps if window is None or step.model_calls <= window]
    seen = None
    for step in steps:
        outcome = _outcome(step, point)
        if seen is None and outcome == "error":
            seen = step.model_calls
        elif seen is not None and outcome == "fixed":
            return step.model_calls - seen
    return 0 if seen is None else max(step.model_calls for step in steps) - seen


def matches_record(step: Executed, result: dict) -> bool:
    """The replayed command returned the recorded code and, if it failed, the same normalized
    error line."""
    found = RETURNCODE.search(step.output)
    recorded = int(found.group(1)) if found else None
    if recorded != result.get("returncode"):
        return False
    before = failure_of(step.command, recorded, step.output)
    after = failure_of(step.command, recorded, result.get("output", ""))
    return (key_of(before) if before else None) == (key_of(after) if after else None)
