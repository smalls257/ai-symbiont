"""Reader for Muse Code session logs (`session.jsonl`, one event-log envelope per line).

The shape comes from Muse Code's own `read-session` skill: a prompt is a `started` run event, the
agent's words are `assistant_message_committed`, and a tool call and its result travel in
`assistant_tool_calls_committed` and `tool_result_batch_committed`, joined by call id.
A line that is not JSON, or a conversation event missing a field, raises ReadError.
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "muse-code"
PRIVATE_SESSIONS = Provenance(dataset="private-sessions", license="none", spark_safe=False)
SESSIONS_PATTERN = "muse/sessions/*/*/*/*/session.jsonl"
_SHELL_TOOLS = frozenset({"bash", "exec_command", "shell"})
_EDIT_TOOLS = frozenset({"edit_file", "write_file", "apply_patch"})
_PATH_KEYS = ("path", "file_path", "target_path", "target", "filename")
logger = logging.getLogger(__name__)


class _MalformedError(Exception):
    """Internal: an event is not in the shape this reader knows. Becomes a ReadError."""


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield the records of one Muse Code session, each tool result folded into its call."""
    events = _run_events(Path(path))
    results = _results_by_call(Path(path), events)
    steps: dict[str, int] = {}
    for line_no, envelope, event in events:
        try:
            for fields in _fields_of(event, results):
                session_id = _session_id(envelope)
                step = steps.get(session_id, 0)
                steps[session_id] = step + 1
                yield _record(envelope, project, session_id, step, fields)
        except _MalformedError as exc:
            raise ReadError(Path(path), line_no, str(exc)) from exc


def session_logs(repo_dir: Path, data_home: Path) -> list[Path]:
    """The main session logs recorded in the workspace `repo_dir`, oldest first.

    `data_home` is the XDG data directory (`~/.local/share`). Each log is opened only as far as
    its `workspace_root` record; subagent logs belong to their parent session and are left out.
    """
    wanted = str(repo_dir.resolve())
    logs = [log for log in data_home.glob(SESSIONS_PATTERN) if _workspace_of(log) == wanted]
    return sorted(logs, key=lambda log: log.stat().st_mtime)


def _workspace_of(log: Path) -> str | None:
    """The `workspace_root` the session recorded, or None when the log never recorded one."""
    with log.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            envelope = _parsed(log, line_no, line)
            if envelope.get("payload_type") == "runtime.session.metadata":
                record = (envelope.get("payload") or {}).get("record")
                root = record.get("workspace_root") if isinstance(record, dict) else None
                return root if isinstance(root, str) else None
    return None


def _parsed(path: Path, line_no: int, line: str) -> dict[str, Any]:
    """One log line as an object; anything else raises ReadError naming file and line."""
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ReadError(path, line_no, f"not valid JSON ({exc.msg})") from exc
    if not isinstance(envelope, dict):
        raise ReadError(path, line_no, "a line must hold one event object")
    return envelope


def _run_events(path: Path) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    """(line, envelope, run event) for each run event; other lines are counted and logged."""
    events = []
    other: Counter[str] = Counter()
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            envelope = _parsed(path, line_no, line)
            payload = envelope.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            event = payload.get("event")
            is_run = (
                envelope.get("payload_type") == "runtime.session" and payload.get("kind") == "run"
            )
            if is_run and isinstance(event, dict):
                events.append((line_no, envelope, event))
            else:
                other[str(envelope.get("payload_type") or envelope.get("retained_frame"))] += 1
    if other:
        logger.info("skipped non-conversation lines in %s: %s", path, dict(other))
    return events


def _results_by_call(
    path: Path, events: list[tuple[int, dict[str, Any], dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Every tool result of the file keyed by the call id it answers."""
    found: dict[str, dict[str, Any]] = {}
    for line_no, _, event in events:
        if event.get("kind") not in ("tool_result_batch_committed", "tool_results_committed"):
            continue
        for result in _list_of_objects(event, "results", path, line_no):
            call_id = result.get("tool_call_id") or result.get("call_id")
            if not isinstance(call_id, str):
                raise ReadError(path, line_no, "a tool result has no call id")
            found[call_id] = result
    return found


def _list_of_objects(event: dict[str, Any], key: str, path: Path, line_no: int) -> list[Any]:
    """`event[key]` as a list of objects, or ReadError."""
    items = event.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ReadError(path, line_no, f"{key!r} must be a list of objects")
    return items


def _session_id(envelope: dict[str, Any]) -> str:
    """The session stream id of an envelope."""
    stream = envelope.get("stream")
    session_id = stream.get("id") if isinstance(stream, dict) else None
    if not isinstance(session_id, str):
        raise _MalformedError("missing the session stream id")
    return session_id


def _record(
    envelope: dict[str, Any], project: str, session_id: str, step: int, fields: dict[str, Any]
) -> Record:
    """A Record from the shared envelope data and the shaped fields."""
    stamp = envelope.get("recorded_at")
    return Record(
        harness=HARNESS,
        project=project,
        session_id=session_id,
        step=step,
        ts=str(stamp) if isinstance(stamp, int) else None,
        provenance=PRIVATE_SESSIONS,
        **fields,
    )


# --- run events to record fields ------------------------------------------------


def _fields_of(event: dict[str, Any], results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The record fields one run event yields; most run events are not conversation."""
    kind = event.get("kind")
    if kind == "started":
        return [{"kind": Kind.USER_TURN, "raw": _text(event, "prompt")}]
    if kind == "assistant_message_committed":
        return [{"kind": Kind.AGENT_TURN, "raw": _text(event, "text")}]
    if kind == "assistant_tool_calls_committed":
        calls = event.get("tool_calls")
        if not isinstance(calls, list) or not all(isinstance(call, dict) for call in calls):
            raise _MalformedError("'tool_calls' must be a list of objects")
        return [_call_fields(call, results) for call in calls]
    return []


def _text(event: dict[str, Any], key: str) -> str:
    """A required string field of an event."""
    value = event.get(key)
    if not isinstance(value, str):
        raise _MalformedError(f"{key!r} must be a string")
    return value


def _call_fields(call: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One tool call with its result folded in."""
    name = call.get("name")
    if not isinstance(name, str):
        raise _MalformedError("a tool call has no name")
    tool = re.split(r"__|\.|/", name)[-1]
    args = _arguments(call.get("args"))
    call_id = call.get("call_id") or call.get("id")
    result = results.get(call_id, {}) if isinstance(call_id, str) else {}
    raw = _result_text(result)
    path = next((args[key] for key in _PATH_KEYS if isinstance(args.get(key), str)), None)
    files = (path,) if path else ()
    if tool in _SHELL_TOOLS:
        command = args.get("cmd") or args.get("command")
        if not isinstance(command, str):
            raise _MalformedError("a shell call has no command")
        return {"kind": Kind.COMMAND, "raw": raw, "command": command, "exit_code": _exit(result)}
    if tool in _EDIT_TOOLS:
        return {"kind": Kind.EDIT, "raw": raw, "files": files, "diff": _edit_diff(args)}
    kind = Kind.READ if tool == "read_file" else Kind.TOOL_RESULT
    return {"kind": kind, "raw": raw, "files": files}


def _edit_diff(args: dict[str, Any]) -> str | None:
    """The change an edit call made: its patch, or `-find` / `+replace` lines."""
    patch = args.get("patch") or args.get("diff") or args.get("input")
    if isinstance(patch, str):
        return patch
    old, new = args.get("find"), args.get("replace")
    if isinstance(old, str) and isinstance(new, str):
        return "".join(f"-{row}\n" for row in old.splitlines()) + "".join(
            f"+{row}\n" for row in new.splitlines()
        )
    return None


def _arguments(args: Any) -> dict[str, Any]:
    """Tool arguments as an object; a JSON string is decoded, anything else is empty."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as exc:
            raise _MalformedError(f"tool arguments are not valid JSON ({exc.msg})") from exc
    return args if isinstance(args, dict) else {}


def _result_text(result: dict[str, Any]) -> str:
    """The output a tool result carries; a shell result's JSON text holds it under `output`."""
    text = _shell_report(result)
    if text is not None and isinstance(text.get("output"), str):
        return text["output"]
    for key in ("text", "output", "result"):
        if isinstance(result.get(key), str):
            return result[key]
    return ""


def _shell_report(result: dict[str, Any]) -> dict[str, Any] | None:
    """A shell result's `text`, when it is a JSON object (Muse Code reports exec chunks so)."""
    text = result.get("text")
    if not isinstance(text, str) or not text.startswith("{"):
        return None
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.info("a result that starts with a brace is plain text, not a report (%s)", exc.msg)
        return None
    return report if isinstance(report, dict) else None


def _exit(result: dict[str, Any]) -> int | None:
    """The exit status the harness reported, else 1 for a result flagged as an error, else None."""
    for source in (_shell_report(result) or {}, result):
        for key in ("exit_code", "exitCode"):
            if isinstance(source.get(key), int):
                return int(source[key])
    return 1 if result.get("is_error") is True else None
