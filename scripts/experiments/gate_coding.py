"""Pick the coding step of a solved trajectory and score a proposed command against it."""

import json
import re
from dataclasses import dataclass
from typing import Any

MIN_PRIOR_ACTIONS = 3  # the step must come after some exploration, never as the first command
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/\S+$", re.MULTILINE)
_DEF_NAME = re.compile(r"\bdef\s+(\w+)")
_EDIT_COMMAND = re.compile(
    r"sed\s+(-[a-zA-Z]*i|--in-place)|\bcat\s*>|>>|\btee\b|\bpatch\b|git\s+apply|perl\s+-[a-z]*p[a-z]*i"
    r"|\.write\(|\.write_text\(|str_replace|\bapply_patch\b"
)


class NoGoldStepError(ValueError):
    """The trajectory has no edit of a patched file after enough exploration."""


@dataclass(frozen=True)
class GoldStep:
    """The real next action: which message it is, the file it edits and that file's functions."""

    message_index: int
    path: str
    functions: frozenset[str]


def patched_functions(patch: str) -> dict[str, frozenset[str]]:
    """Patched file -> function names (`def`) named in its hunk headers or added lines."""
    found: dict[str, frozenset[str]] = {}
    for block in re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE):
        path = _DIFF_FILE.search(block)
        if path is None:
            continue
        names = set()
        for line in block.splitlines():
            if line.startswith("@@"):
                names.update(_DEF_NAME.findall(line.split("@@")[-1]))
            elif line.startswith("+") and not line.startswith("+++"):
                names.update(_DEF_NAME.findall(line))
        found[path[1]] = frozenset(names)
    return found


def mentions_path(command: str, path: str) -> bool:
    """The command names the file by its repo path or by its bare file name."""
    base = path.rsplit("/", 1)[-1]
    return (
        path in command or re.search(rf"(?<![\w.-]){re.escape(base)}(?![\w])", command) is not None
    )


class MalformedToolCallError(ValueError):
    """An assistant message has a tool call whose arguments carry no readable command."""


def bash_command(message: dict[str, Any]) -> str | None:
    """The first bash command of an assistant message; None only when it made no tool call."""
    calls = message.get("tool_calls") or []
    if not calls:
        return None
    try:
        return str(json.loads(calls[0]["function"]["arguments"])["command"])
    except (KeyError, ValueError, TypeError) as error:
        raise MalformedToolCallError(f"unreadable tool call: {error!r}") from error


def find_gold_step(messages: list[dict[str, Any]], patch: str) -> GoldStep:
    """First edit of a patched file after exploration; the command must carry the full repo path."""
    patched = patched_functions(patch)
    actions = 0
    for index, message in enumerate(messages):
        command = bash_command(message) if message["role"] == "assistant" else None
        if command is None:
            continue
        actions += 1
        if actions <= MIN_PRIOR_ACTIONS or not _EDIT_COMMAND.search(command):
            continue
        for path, names in patched.items():
            if path in command:  # the repo path itself: a scratch copy of the file is not an edit
                return GoldStep(index, path, names)
    raise NoGoldStepError("no edit of a patched file after exploration")


def proposal_matches(command: str | None, gold: GoldStep) -> bool:
    """Same file as the real action and, if that file's functions are known, one of them."""
    if command is None or not mentions_path(command, gold.path):
        return False
    if not gold.functions:
        return True
    return any(re.search(rf"\b{re.escape(name)}\b", command) for name in gold.functions)


def proposal_names_file(command: str | None, gold: GoldStep) -> bool:
    """Secondary, looser reading: same file only (reported, never used in the decision rule)."""
    return command is not None and mentions_path(command, gold.path)
