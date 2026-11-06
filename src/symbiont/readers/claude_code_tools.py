"""How each Claude Code tool call becomes record fields: shell command, read, edit, write.

Split from the reader so the event loop and the per-tool shapes can each be read alone.
"""

import difflib
from collections.abc import Callable
from typing import Any

from symbiont.readers.claude_code_fields import MalformedError, optional_text, require, require_text
from symbiont.records.schema import Kind


def make_relative(cwd: str | None) -> Callable[[str], str]:
    """A function that strips the session's cwd from absolute paths."""

    def relative(path: str) -> str:
        """The path relative to the session's cwd when it is inside it."""
        if cwd and path.startswith(cwd.rstrip("/") + "/"):
            return path[len(cwd.rstrip("/")) + 1 :]
        return path

    return relative


def _bash(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A shell command action."""
    return {"kind": Kind.COMMAND, "command": require_text(args, "command")}


def _read_file(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A file-view action with the lines shown."""
    return {
        "kind": Kind.READ,
        "files": (relative(require_text(args, "file_path")),),
        "line_range": _read_range(args),
    }


def _read_range(args: dict[str, Any]) -> tuple[int, int] | None:
    """(first, last) line shown from offset and limit; None for a whole-file read."""
    offset, limit = args.get("offset"), args.get("limit")
    if offset is None and limit is None:
        return None
    if not all(isinstance(v, int) for v in (offset or 1, limit or 1)):
        raise MalformedError(f"Read offset and limit must be integers, got {offset!r}, {limit!r}")
    first = offset or 1
    return (first, first + limit - 1) if limit else (first, -1)


def _edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """An edit action with a snippet-level diff."""
    path = relative(require_text(args, "file_path"))
    pairs = [(require_text(args, "old_string"), optional_text(args, "new_string"))]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _multi_edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """One edit action for a MultiEdit call, its diffs joined in order."""
    path = relative(require_text(args, "file_path"))
    edits = require(args, "edits")
    if not isinstance(edits, list):
        raise MalformedError("MultiEdit 'edits' must be a list")
    pairs = [(require_text(e, "old_string"), optional_text(e, "new_string")) for e in edits]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _write(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """A whole-file write as an edit against /dev/null."""
    path = relative(require_text(args, "file_path"))
    return {
        "kind": Kind.EDIT,
        "files": (path,),
        "diff": _diff(path, [("", require_text(args, "content"))], "/dev/null"),
    }


def _notebook_edit(
    name: str, args: dict[str, Any], relative: Callable[[str], str]
) -> dict[str, Any]:
    """A notebook edit action; the previous cell text is not logged, so there is no diff."""
    return {"kind": Kind.EDIT, "files": (relative(require_text(args, "notebook_path")),)}


def other_tool(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """Search, planning and MCP tools: kept as results so nothing is dropped."""
    return {"kind": Kind.TOOL_RESULT, "command": name}


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
