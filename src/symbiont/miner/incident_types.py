"""The shapes of an incident card: why it is noise, how it ended, and the trigger it implies."""

from dataclasses import dataclass
from enum import StrEnum

from symbiont.miner.painpoint import Signal

NO_SITUATION = ("", "", "")


class NoiseReason(StrEnum):
    """Why an incident is not worth a look."""

    LOOK_AROUND = "look_around"  # a probe program failed
    INTERRUPT = "interrupt"
    THROWAWAY_SCRIPT = "throwaway_script"
    DELIBERATE_REPRO = (
        "deliberate_repro"  # a throwaway script failed, the code was edited, it passed
    )
    PLAIN_RETRY = "plain_retry"  # passed when run again with nothing changed
    EMPTY_CORRECTION = "empty_correction"


class Outcome(StrEnum):
    """How an incident ended."""

    FIXED_IN_CODE = "fixed_in_code"
    ENVIRONMENT_FIXED = "environment_fixed"  # a setup command came before the pass
    CORRECTED_COMMAND = "corrected_command"
    PASSED_ON_RETRY = "passed_on_retry"
    NEVER_FIXED = "never_fixed"
    DEVELOPER_STEPPED_IN = "developer_stepped_in"  # a correction


class TriggerKind(StrEnum):
    """When the agent should hear a lesson."""

    RUNNING = "running"  # about to run a program, optionally on a path
    EDITING = "editing"  # about to edit files under a path
    BEFORE = "before"  # about to do a named step: "before git push"


@dataclass(frozen=True)
class Incident:
    """One occurrence, told in plain language."""

    session_id: str
    step: int
    signal: Signal
    what_happened: str  # one sentence
    first_wrong: str  # corrections: the agent's first upstream action that went wrong; "" if none
    cost_steps: int  # corrections: agent actions from first_wrong to the correction
    what_fixed_it: str  # one sentence
    outcome: Outcome
    noise: NoiseReason | None  # None means worth a look
    topic: str  # the session's topic name; "" before topics exist
    files: tuple[str, ...]
    # (kind, program, path) of the action it is about: the failed command, or first_wrong.
    situation: tuple[str, str, str]


@dataclass(frozen=True)
class Trigger:
    """The situation a group of incidents shares."""

    kind: TriggerKind
    program: str  # "" for EDITING
    path: str  # the common directory; "" when the occurrences share none
    words: str  # the plain phrase shown and spoken
