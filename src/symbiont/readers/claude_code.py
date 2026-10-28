"""Reader for Claude Code session logs.

Input is JSONL, one event per line, in the shape Claude Code writes under
`~/.claude/projects/*` and SWE-chat republishes: `type` ("user" or "assistant"),
`sessionId`, `timestamp`, optional `cwd`, and `message` whose `content` is text
or a list of blocks (`text`, `tool_use`, `tool_result`). A tool result answers
its `tool_use` by id and travels in that action's `raw`. SWE-chat marks user
pushback with `prompt_pushback`; it becomes the "correction" tag.

Subagent events share the session id, and meta user lines become user turns.
Events other than user and assistant that carry no `message` are metadata:
they are skipped and counted per type, and the counts are logged per file.
A non-conversation type that does carry a `message` raises ReadError.

Three entry points differ only in provenance. `read` is for the owner's private
sessions and is the default: unknown privacy is never shareable.
"""

import difflib
import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG, RECALL_TOOL_NAME, split_our_output
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "claude-code"
PRIVATE_SESSIONS = Provenance(dataset="private-sessions", license="none", spark_safe=False)
SWE_CHAT = Provenance(dataset="swe-chat", license="see-dataset-card", spark_safe=False)
OPEN_SWE_TRACES = Provenance(dataset="open-swe-traces", license="see-dataset-card", spark_safe=True)

CORRECTION = "correction"
_CONVERSATION_TYPES = ("user", "assistant")
logger = logging.getLogger(__name__)
_EXIT_CODE = re.compile(r"^Exit code (-?\d+)")


class _MalformedError(Exception):
    """Internal: an event is not in the shape this reader knows. Becomes a ReadError."""


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield records of the owner's private sessions (never spark safe)."""
    return _read(path, project, PRIVATE_SESSIONS)


def read_swe_chat(path: Path, project: str) -> Iterator[Record]:
    """Yield records of SWE-chat sessions (never spark safe)."""
    return _read(path, project, SWE_CHAT)


def read_open_swe_traces(path: Path, project: str) -> Iterator[Record]:
    """Yield records of public Open-SWE-Traces Claude Code rows (spark safe)."""
    return _read(path, project, OPEN_SWE_TRACES)


def _read(path: Path, project: str, provenance: Provenance) -> Iterator[Record]:
    events = _conversation_events(Path(path))
    results = _results_by_call(path, events)
    source = _Source(project, provenance)
    steps: dict[str, int] = {}
    for line_no, event in events:
        try:
            for fields in _event_records(event, results):
                session_id = _require_text(event, "sessionId")
                step = steps.get(session_id, 0)
                steps[session_id] = step + 1
                yield _record(event, source, session_id, step, fields)
        except _MalformedError as exc:
            raise ReadError(path, line_no, str(exc)) from exc


def _conversation_events(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """User and assistant events; metadata events are counted and logged, not dropped silently."""
    events = []
    skipped: Counter[str] = Counter()
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReadError(path, line_no, f"not valid JSON ({exc.msg})") from exc
            if not isinstance(event, dict):
                raise ReadError(path, line_no, "a line must hold one event object")
            if _is_metadata(path, line_no, event):
                skipped[event["type"]] += 1
            else:
                events.append((line_no, event))
    if skipped:
        logger.info("skipped metadata events in %s: %s", path, dict(skipped))
    return events


def _is_metadata(path: Path, line_no: int, event: dict[str, Any]) -> bool:
    kind = event.get("type")
    if not isinstance(kind, str):
        message = "missing 'type'" if kind is None else "'type' must be a string"
        raise ReadError(path, line_no, message)
    has_message = event.get("message") is not None
    if kind in _CONVERSATION_TYPES:
        if not has_message:
            raise ReadError(path, line_no, f"{kind!r} event has no 'message'")
        return False
    if has_message:
        raise ReadError(path, line_no, f"unknown event type {kind!r}")
    return True


def _results_by_call(
    path: Path, events: list[tuple[int, dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    results = {}
    for line_no, event in events:
        try:
            results.update(_event_results(event))
        except _MalformedError as exc:
            raise ReadError(path, line_no, str(exc)) from exc
    return results


def _event_results(event: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _require_text(block, "tool_use_id"): block
        for block in _blocks(event)
        if block.get("type") == "tool_result"
    }


def _require(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict) or mapping.get(key) is None:
        raise _MalformedError(f"missing {key!r}")
    return mapping[key]


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _MalformedError(f"{field!r} must be a string, got {type(value).__name__}")
    return value


def _require_text(mapping: Any, key: str) -> str:
    return _require_str(_require(mapping, key), key)


def _optional_text(mapping: dict[str, Any], key: str) -> str:
    """A field the harness may omit; empty then, but never a non-string."""
    value = mapping.get(key)
    return "" if value is None else _require_str(value, key)


def _blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = _require(_require(event, "message"), "content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise _MalformedError("message 'content' must be text or a list of blocks")
    return content


@dataclass(frozen=True)
class _Source:
    project: str
    provenance: Provenance


def _record(
    event: dict[str, Any], source: _Source, session_id: str, step: int, fields: dict[str, Any]
) -> Record:
    return Record(
        harness=HARNESS,
        project=source.project,
        session_id=session_id,
        step=step,
        ts=event.get("timestamp"),
        provenance=source.provenance,
        **fields,
    )


# --- events to record fields ----------------------------------------------------


def _event_records(
    event: dict[str, Any], results: dict[str, dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    _optional_text(event, "cwd")
    if event["type"] == "user":
        yield from _user_turns(event)
    else:
        yield from _assistant_records(event, results)


def _user_turns(event: dict[str, Any]) -> Iterator[dict[str, Any]]:
    texts = [_require_text(b, "text") for b in _blocks(event) if b.get("type") == "text"]
    if not texts:
        return  # tool results only: they are folded into the action they answer
    yield {"kind": Kind.USER_TURN, "raw": "\n".join(texts), "tags": _pushback_tags(event)}


def _pushback_tags(event: dict[str, Any]) -> tuple[str, ...]:
    flag = event.get("prompt_pushback")
    if flag is None or flag is False or flag == "":
        return ()
    if flag is True or isinstance(flag, str):
        return (CORRECTION,)
    raise _MalformedError(f"prompt_pushback must be true/false or a label, got {flag!r}")


def _assistant_records(
    event: dict[str, Any], results: dict[str, dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    cwd = _optional_text(event, "cwd") or None
    for block in _blocks(event):
        kind = block.get("type")
        if kind == "text":
            yield {"kind": Kind.AGENT_TURN, "raw": _require_text(block, "text")}
        elif kind == "tool_use":
            yield from _tool_use(block, results.get(_require_text(block, "id")), cwd)
        elif kind != "thinking":
            raise _MalformedError(f"unknown assistant block type {kind!r}")


def _tool_use(
    block: dict[str, Any], result: dict[str, Any] | None, cwd: str | None
) -> Iterator[dict[str, Any]]:
    """The harness's action, then our own text from its result as a separate record."""
    name = _require_text(block, "name")
    args = _require(block, "input")
    if not isinstance(args, dict):
        raise _MalformedError(f"tool input of {name!r} must be an object")
    text = _result_content(result)
    # Our recall answer is ours from the first character.
    own, ours = ("", text) if name == RECALL_TOOL_NAME else split_our_output(text)
    fields = _TOOLS.get(name, _other_tool)(name, args, _make_relative(cwd))
    fields["raw"] = own
    fields["exit_code"] = _exit_code(fields["kind"], result, own)
    yield fields
    if ours:
        yield {"kind": Kind.TOOL_RESULT, "raw": ours, "tags": (OUR_OUTPUT_RECORD_TAG,)}


def _result_content(result: dict[str, Any] | None) -> str:
    if result is None:
        return ""
    content = result.get("content")
    if content is None or isinstance(content, str):
        return content or ""
    if isinstance(content, list) and all(isinstance(b, dict) for b in content):
        return "\n".join(str(b.get("text", "")) for b in content)
    raise _MalformedError("tool_result 'content' must be text or a list of blocks")


def _exit_code(kind: Kind, result: dict[str, Any] | None, raw: str) -> int | None:
    """None when no result came back or the harness gave no code: unknown, not success."""
    if result is None or kind == Kind.TOOL_RESULT:
        return None
    if kind == Kind.COMMAND:
        found = _EXIT_CODE.match(raw)
        if found:
            return int(found.group(1))
        return None if result.get("is_error") else 0
    return 1 if result.get("is_error") else 0


# --- tools ---------------------------------------------------------------------


def _make_relative(cwd: str | None) -> Callable[[str], str]:
    def relative(path: str) -> str:
        if cwd and path.startswith(cwd.rstrip("/") + "/"):
            return path[len(cwd.rstrip("/")) + 1 :]
        return path

    return relative


def _bash(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    return {"kind": Kind.COMMAND, "command": _require_text(args, "command")}


def _read_file(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    return {
        "kind": Kind.READ,
        "files": (relative(_require_text(args, "file_path")),),
        "line_range": _read_range(args),
    }


def _read_range(args: dict[str, Any]) -> tuple[int, int] | None:
    offset, limit = args.get("offset"), args.get("limit")
    if offset is None and limit is None:
        return None
    if not all(isinstance(v, int) for v in (offset or 1, limit or 1)):
        raise _MalformedError(f"Read offset and limit must be integers, got {offset!r}, {limit!r}")
    first = offset or 1
    return (first, first + limit - 1) if limit else (first, -1)


def _edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    path = relative(_require_text(args, "file_path"))
    pairs = [(_require_text(args, "old_string"), _optional_text(args, "new_string"))]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _multi_edit(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    path = relative(_require_text(args, "file_path"))
    edits = _require(args, "edits")
    if not isinstance(edits, list):
        raise _MalformedError("MultiEdit 'edits' must be a list")
    pairs = [(_require_text(e, "old_string"), _optional_text(e, "new_string")) for e in edits]
    return {"kind": Kind.EDIT, "files": (path,), "diff": _diff(path, pairs, f"a/{path}")}


def _write(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    path = relative(_require_text(args, "file_path"))
    return {
        "kind": Kind.EDIT,
        "files": (path,),
        "diff": _diff(path, [("", _require_text(args, "content"))], "/dev/null"),
    }


def _notebook_edit(
    name: str, args: dict[str, Any], relative: Callable[[str], str]
) -> dict[str, Any]:
    # The notebook's previous cell text is not logged, so there is no diff.
    return {"kind": Kind.EDIT, "files": (relative(_require_text(args, "notebook_path")),)}


def _other_tool(name: str, args: dict[str, Any], relative: Callable[[str], str]) -> dict[str, Any]:
    """Search, planning and MCP tools: kept as results so nothing is dropped."""
    return {"kind": Kind.TOOL_RESULT, "command": name}


def _diff(path: str, pairs: list[tuple[str, str]], old_name: str) -> str:
    # Claude Code does not record where old_string sits; hunk numbers are snippet-relative.
    return "".join(
        "".join(difflib.unified_diff(_lines(old), _lines(new), old_name, f"b/{path}"))
        for old, new in pairs
    )


def _lines(text: str) -> list[str]:
    return [line + "\n" for line in text.splitlines()]


_TOOLS: dict[str, Callable[[str, dict[str, Any], Callable[[str], str]], dict[str, Any]]] = {
    "Bash": _bash,
    "Read": _read_file,
    "Edit": _edit,
    "MultiEdit": _multi_edit,
    "Write": _write,
    "NotebookEdit": _notebook_edit,
}
