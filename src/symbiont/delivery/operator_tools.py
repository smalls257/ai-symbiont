"""The `/symbiont` actions (allow, mine, status ...) as MCP tools.

Muse Code sandboxes the model's shell away from the data directory; the MCP server runs outside
it. Each tool is only the argv of the `symbiont` subcommand of the same name, so tool and command
line cannot drift apart. Running the argv is injected (`Operate`), so this module needs no service.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PRIORITIES = ["low", "normal", "high"]


@dataclass(frozen=True)
class Outcome:
    """What a subcommand printed, and whether it failed."""

    text: str
    failed: bool = False


Operate = Callable[[list[str]], Outcome]
_STRING = {"type": "string"}
_NO_ARGUMENTS: dict[str, Any] = {}


@dataclass(frozen=True)
class OperatorTool:
    """One tool: the subcommand it runs, whether that subcommand knows `--port`, its schema."""

    name: str
    description: str
    command: tuple[str, ...]
    takes_port: bool = False
    properties: dict[str, Any] | None = None
    required: tuple[str, ...] = ()

    def listed(self) -> dict[str, Any]:
        """The tool as MCP lists it."""
        schema = {
            "type": "object",
            "properties": self.properties or {},
            "required": list(self.required),
            "additionalProperties": False,
        }
        return {"name": self.name, "description": self.description, "inputSchema": schema}


OPERATOR_TOOLS = [
    OperatorTool(
        "symbiont_status",
        "Whether symbiont is running, and what it knows about this repository.",
        ("status",),
        takes_port=True,
    ),
    OperatorTool(
        "symbiont_allow",
        "Switch symbiont on for this repository (the developer's answer: yes).",
        ("repo", "allow"),
    ),
    OperatorTool(
        "symbiont_decline",
        "Keep symbiont off for this repository (the developer's answer: no).",
        ("repo", "decline"),
    ),
    OperatorTool(
        "symbiont_mine",
        "Learn from this repository's past Claude Code and Muse Code sessions (needs "
        "symbiont_allow first). Opens the dashboard unless the developer turned that off, and "
        "returns its address with a progress summary; a long job keeps running in the service. "
        "When setting a repository up, next find the developer's past corrections "
        "(symbiont_correction_candidates, then symbiont_save_corrections) before symbiont_nightly.",
        ("repo", "mine"),
        takes_port=True,
    ),
    OperatorTool(
        "symbiont_nightly",
        "Train this repository's checker on its lessons, on this machine (nothing is uploaded). "
        "Sets up first if needed, then trains in the background and returns within a minute; "
        "training takes 1-4 minutes, and symbiont_status reports its progress. With no base and "
        "kit it reuses a kit that is already built, else finds the model on this machine, else "
        "downloads it (about 2.5 GB from Hugging Face) in the background first. Run it after the "
        "developer's past corrections are saved, so the checker learns from them too.",
        ("nightly", "start"),
        properties={
            "base": {**_STRING, "description": "folder of the downloaded Llama-3.2-1B-Instruct"},
            "kit": {**_STRING, "description": "the downloaded nightly-kit folder"},
        },
    ),
    OperatorTool(
        "symbiont_dashboard",
        "The address of this repository's dashboard. Tell the developer the address.",
        ("dashboard",),
        takes_port=True,
    ),
    OperatorTool(
        "symbiont_why",
        "Why the last note fired, and what it rested on.",
        ("why",),
    ),
    OperatorTool(
        "symbiont_mute",
        "Stop notes about the kind of trouble the last note was about.",
        ("mute",),
    ),
    OperatorTool(
        "symbiont_forget",
        "Delete the lessons behind the last note, or the one lesson named, and keep them silenced.",
        ("forget",),
        properties={"lesson_id": {**_STRING, "description": "an id from symbiont_lessons"}},
    ),
    OperatorTool(
        "symbiont_lessons",
        "List this repository's stored lessons with their ids.",
        ("lessons",),
    ),
    OperatorTool(
        "symbiont_context",
        "Put the developer's own words in front of a lesson's note.",
        ("context", "add"),
        properties={
            "lesson": {**_STRING, "description": 'an id from symbiont_lessons, or "last"'},
            "words": {
                **_STRING,
                "description": "what symbiont should say, in the developer's words",
            },
            "intentional": {"type": "boolean", "description": "the failure is on purpose"},
            "priority": {"type": "string", "enum": PRIORITIES},
        },
        required=("lesson", "words"),
    ),
    OperatorTool(
        "symbiont_settings",
        "Show which histories the session's model may read when looking for corrections.",
        ("settings", "show"),
    ),
    OperatorTool(
        "symbiont_learn_from_prs",
        "The steps for learning lessons from recent pull-request reviews and CI failures.",
        ("learn-from-prs",),
    ),
]
OPERATOR_BY_NAME = {tool.name: tool for tool in OPERATOR_TOOLS}


def listed_operator_tools() -> list[dict[str, Any]]:
    """The operator tools as MCP lists them."""
    return [tool.listed() for tool in OPERATOR_TOOLS]


def operator_argv(name: str, arguments: dict[str, Any], project: str, port: int) -> list[str]:
    """The `symbiont` argv a tool call stands for; ValueError names a bad argument."""
    tool = OPERATOR_BY_NAME[name]
    allowed = set(tool.properties or {})
    if unknown := set(arguments) - allowed:
        raise ValueError(f"{name} does not take {sorted(unknown)}; it takes {sorted(allowed)}")
    if missing := [key for key in tool.required if key not in arguments]:
        raise ValueError(f"{name} needs {missing}")
    argv = [*tool.command, *_positionals(name, arguments), "--project", project]
    if tool.takes_port:
        argv += ["--port", str(port)]
    return argv + _options(name, arguments)


def _positionals(name: str, arguments: dict[str, Any]) -> list[str]:
    """The arguments the subcommand takes by position."""
    if name == "symbiont_context":
        return [_text(arguments, "lesson"), _text(arguments, "words")]
    return []


def _options(name: str, arguments: dict[str, Any]) -> list[str]:
    """The arguments the subcommand takes as options."""
    if name == "symbiont_forget" and "lesson_id" in arguments:
        return ["--lesson", _text(arguments, "lesson_id")]
    if name == "symbiont_nightly":
        return _nightly_options(arguments)
    if name != "symbiont_context":
        return []
    found = ["--intentional"] if arguments.get("intentional") is True else []
    if "priority" in arguments:
        priority = arguments["priority"]
        if priority not in PRIORITIES:
            raise ValueError(f"priority is one of {PRIORITIES}")
        found += ["--priority", priority]
    return found


def _text(arguments: dict[str, Any], key: str) -> str:
    """A required string argument; ValueError when it is not one."""
    value = arguments[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _nightly_options(arguments: dict[str, Any]) -> list[str]:
    """`--base` and `--kit-files` when given; the subcommand needs both or neither."""
    if ("base" in arguments) != ("kit" in arguments):
        raise ValueError("symbiont_nightly needs base and kit together, or neither")
    if "base" not in arguments:
        return []
    return ["--base", _text(arguments, "base"), "--kit-files", _text(arguments, "kit")]
