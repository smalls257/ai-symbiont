"""How each Claude Code tool call becomes record fields: shell command, read, edit, write.

Split from the reader so the event loop and the per-tool shapes can each be read alone.
"""

import difflib
from collections.abc import Callable
from typing import Any

from symbiont.readers.claude_code_fields import RefusedCallError
from symbiont.records.schema import Kind


def make_relative(cwd: str | None) -> Callable[[str], str]:
    """A function that strips the session's cwd from absolute paths."""

    def relative(path: str) -> str:
        """The path relative to the session's cwd when it is inside it."""
        if cwd and path.startswith(cwd.rstrip("/") + "/"):
            return path[len(cwd.rstrip("/")) + 1 :]
        return path

    return relative


def _needed(args: dict[str, Any], key: str) -> str:
    """A text argument the tool needs; its absence or wrong type is a call the tool rejects."""
    value = args.get(key)
    if not isinstance(value, str):
        raise RefusedCallError(f"tool call without text {key!r}")
    return value


def _optional(args: dict[str, Any], key: str) -> str:
    """A text argument the tool may omit; a non-text one is still a call the tool rejects."""
    value = args.get(key)
    if value is not None and not isinstance(value, str):
        raise RefusedCallError(f"tool argument {key!r} must be text")
    return value or ""


def _bash(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A shell command action."""
    return {"kind": Kind.COMMAND, "command": _needed(args, "command")}


def _read_file(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A file-view action with the lines shown."""
    return {
        "kind": Kind.READ,
        "files": (relative(_needed(args, "file_path")),),
        "line_range": _read_range(args),
    }


def _read_range(args: dict[str, Any]) -> tuple[int, int] | None:
    """(first, last) line shown from offset and limit; None for a whole-file read."""
    offset, limit = args.get("offset"), args.get("limit")
    if offset is None and limit is None:
        return None
    if not all(_is_integer(v) for v in (offset or 1, limit or 1)):
        raise RefusedCallError(f"Read offset and limit must be integers, got {offset!r}, {limit!r}")
    first = offset or 1
    return (first, first + limit - 1) if limit else (first, -1)


def _is_integer(value: Any) -> bool:
    """True for a real integer; a boolean is not one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """An edit action with a snippet-level diff."""
    path = relative(_needed(args, "file_path"))
    pairs = [(_needed(args, "old_string"), _optional(args, "new_string"))]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _multi_edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """One edit action for a MultiEdit call, its diffs joined in order."""
    path = relative(_needed(args, "file_path"))
    edits = args.get("edits")
    if not isinstance(edits, list) or not all(isinstance(e, dict) for e in edits):
        raise RefusedCallError("MultiEdit 'edits' must be a list of edits")
    pairs = [(_needed(e, "old_string"), _optional(e, "new_string")) for e in edits]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _write(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A whole-file write as an edit against /dev/null."""
    path = relative(_needed(args, "file_path"))
    return {
        "kind": Kind.EDIT,
        "files": (path,),
        "diff": _diff(path, [("", _needed(args, "content"))], "/dev/null"),
    }


def _notebook_edit(
    name: str, args: dict[str, Any], relative: Callable[[str], str]
) -> dict[str, Any]:
    """A notebook edit action; the previous cell text is not logged, so there is no diff."""
    return {"kind": Kind.EDIT, "files": (relative(_needed(args, "notebook_path")),)}


def other_tool(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """Search, planning and MCP tools: kept as results so nothing is dropped."""
    return {"kind": Kind.TOOL_RESULT, "command": name}


_REFUSED_KINDS = {"Bash": Kind.COMMAND, "Read": Kind.READ}


def refused_call(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """The record fields of a call the tool rejected: a failed action, never a fix or churn.

    Exit 1 and no diff are how the miner knows nothing changed. The path is kept when it is text.
    """
    kind = _REFUSED_KINDS.get(name, Kind.EDIT)
    path = args.get("notebook_path") if name == "NotebookEdit" else args.get("file_path")
    files = (relative(path),) if isinstance(path, str) else ()
    return {"kind": kind, "files": files, "diff": None, "exit_code": 1}


def _diff(path: str, pairs: list[tuple[str, str]], old_name: str) -> str:
    """Unified diff of each old/new pair, labeled with the file's path."""
    # Claude Code does not record where old_string sits; hunk numbers are snippet-relative.
    return "".join(
        "".join(difflib.unified_diff(_lines(old), _lines(new), old_name, f"b/{path}"))
        for old, new in pairs
    )


def _lines(text: str) -> list[str]:
    """Text split into newline-terminated lines for difflib."""
    return [line + "\n" for line in text.splitlines()]


TOOLS: dict[str, Callable[[str, dict[str, Any], Callable[[str], str]], dict[str, Any]]] = {
    "Bash": _bash,
    "Read": _read_file,
    "Edit": _edit,
    "MultiEdit": _multi_edit,
    "Write": _write,
    "NotebookEdit": _notebook_edit,
}
