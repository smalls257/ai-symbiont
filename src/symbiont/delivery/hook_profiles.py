"""How hooks talk to each harness: tool names, exit-status rules, echo and project naming.

`hooks.py` used to hold the union of every harness's tool names and branch on harness ids; a new
harness is now one `HookProfile` entry here. The tool-name sets are split per harness so one
harness's name cannot misclassify another's call.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from symbiont.delivery.claude_code_payload import shell_exit_code
from symbiont.delivery.hook_vocab import HookEvent, NoteStyle
from symbiont.delivery.install.claude_code import claude_code_install
from symbiont.delivery.install.muse_code import muse_code_install
from symbiont.delivery.install.transaction import HarnessInstall
from symbiont.readers.harnesses import UnknownHarnessError


class EchoPolicy(StrEnum):
    """Whether the model is asked to repeat a shown note to the developer."""

    # Muse Code's TUI flashes `systemMessage` for a few seconds, so the developer never reads the
    # note; the model says it in its reply, where the transcript keeps it. Claude Code shows
    # `systemMessage` itself.
    ASK_MODEL_TO_REPEAT = "ask_model_to_repeat"
    NONE = "none"


class ProjectNaming(StrEnum):
    """How a hook names the project when its cwd may be a subdirectory (project_identity.py)."""

    CWD_NAME = "cwd_name"
    GIT_ROOT_WHEN_KNOWN = "git_root_when_known"


@dataclass(frozen=True)
class ShellOutcome:
    """A finished shell call as a hook saw it, for the harness's own exit-status rule."""

    event: HookEvent
    data: dict[str, Any]  # the hook payload
    printed: Any  # the tool response, JSON text already opened
    raw: str  # what the tool printed, as text


@dataclass(frozen=True)
class HookProfile:
    """Everything the shared hook code needs to know about one harness."""

    harness_id: str
    edit_tools: frozenset[str]
    shell_tools: frozenset[str]
    read_tools: frozenset[str]
    shell_exit: Callable[[ShellOutcome], int | None]
    echo: EchoPolicy
    project_naming: ProjectNaming
    install: Callable[[NoteStyle], HarnessInstall]


def reported_exit_code(outcome: ShellOutcome) -> int | None:
    """What the harness reported; a failure with no code is 1, a success is never assumed 0."""
    response = outcome.printed
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode"):
            if isinstance(response.get(key), int):
                return int(response[key])
    return 1 if outcome.event is HookEvent.POST_TOOL_USE_FAILURE else None


def claude_code_exit_code(outcome: ShellOutcome) -> int | None:
    """Claude Code's payloads carry no code on success and flag an interrupt; see its module."""
    if "transcript_path" in outcome.data:  # sent on every real Claude Code hook
        failed = outcome.event is HookEvent.POST_TOOL_USE_FAILURE
        return shell_exit_code(outcome.data, outcome.raw, failed=failed)
    return reported_exit_code(outcome)


# Muse Code names its tools in snake_case [measured from live hook payloads: `bash`, `read_file`];
# `powershell` is its shell tool on Windows [measured on Windows 11, Muse 1.4.14].
_MUSE_CODE = HookProfile(
    harness_id="muse_code",
    edit_tools=frozenset({"edit_file", "write_file", "apply_patch"}),
    shell_tools=frozenset({"shell", "bash", "exec_command", "powershell"}),
    read_tools=frozenset({"read_file"}),
    shell_exit=reported_exit_code,
    echo=EchoPolicy.ASK_MODEL_TO_REPEAT,
    project_naming=ProjectNaming.CWD_NAME,
    install=muse_code_install,
)
_CLAUDE_CODE = HookProfile(
    harness_id="claude_code",
    edit_tools=frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"}),
    shell_tools=frozenset({"Bash", "PowerShell"}),
    read_tools=frozenset({"Read"}),
    shell_exit=claude_code_exit_code,
    echo=EchoPolicy.NONE,
    project_naming=ProjectNaming.GIT_ROOT_WHEN_KNOWN,
    install=claude_code_install,
)
PROFILES: Mapping[str, HookProfile] = {p.harness_id: p for p in (_MUSE_CODE, _CLAUDE_CODE)}


def profile(harness_id: str, known: Mapping[str, HookProfile] = PROFILES) -> HookProfile:
    """The hook profile of a harness; an unknown id raises, it never defaults."""
    if harness_id not in known:
        raise UnknownHarnessError(f"unknown harness {harness_id!r}; known: {', '.join(known)}")
    return known[harness_id]


# Wrappers that are no hook harness but send a hook-shaped payload, and the profile whose tool
# names and exit-status rule that payload follows. The mini-SWE-agent wrapper builds Claude
# Code's shape (`Bash`, `tool_response.exit_code`).
_BORROWED_VOCABULARY = {"mini_swe_agent": "claude_code"}


def tool_vocabulary(harness_id: str, known: Mapping[str, HookProfile] = PROFILES) -> HookProfile:
    """The profile that reads a record's tool calls: the harness's own, or the one it borrows."""
    return profile(_BORROWED_VOCABULARY.get(harness_id, harness_id), known)
