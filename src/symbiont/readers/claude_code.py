"""Reader for Claude Code session logs (JSONL, one event per line).

A tool result travels in the `raw` of the action it answers. A tool call the tool itself would
reject is kept as a refused action; unmineable content is skipped, counted and logged; any
other malformed shape raises ReadError. `read` is for private sessions: never shareable.
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from symbiont.readers.claude_code_fields import (
    MalformedError,
    RefusedCallError,
    optional_text,
    origin_kind,
    require,
    require_text,
)
from symbiont.readers.claude_code_skips import REFUSED_CALLS, report_skips
from symbiont.readers.claude_code_tags import (
    TITLE_EVENT,
    branch_tags,
    fallback_title,
    pushback_tags,
    remember_title,
    session_title,
)
from symbiont.readers.claude_code_tools import TOOLS, make_relative, other_tool, refused_call
from symbiont.readers.errors import ReadError
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG, RECALL_TOOL_NAMES, split_our_output
from symbiont.records.output_failure import exit_code_with_output
from symbiont.records.schema import Kind, Provenance, Record
from symbiont.records.session_tags import CREATED_TAG, title_tag

HARNESS = "claude-code"
PRIVATE_SESSIONS = Provenance(dataset="private-sessions", license="none", remote_safe=False)
SWE_CHAT = Provenance(dataset="swe-chat", license="see-dataset-card", remote_safe=False)
OPEN_SWE_TRACES = Provenance(
    dataset="open-swe-traces", license="see-dataset-card", remote_safe=True
)

_CONVERSATION_TYPES = ("user", "assistant")
logger = logging.getLogger(__name__)
_EXIT_CODE = re.compile(r"^Exit code (-?\d+)")
# Fields Claude Code sets on user events that are not the developer's own typing.
_NOT_TYPED_FLAGS = {
    "isCompactSummary": "compaction summary",
    "isMeta": "caveat or meta line",
    "isSidechain": "sidechain prompt",
}
# Claude Code logs the API requests it sends as events whose `message` is the request body.
# They are bookkeeping, not turns: skip and count them. Any other non-conversation type with a
# message is still new conversation-shaped content and raises.
_REQUEST_LOG_TYPES = ("api-request-blob", "api-request", "api-request-shape")
# `origin.kind` of user events other than the developer's typing: background-agent notifications
# and other sessions' messages arrive as user events but are not the developer's words. Any
# kind not named here is counted under its own name.
_HUMAN_ORIGIN = "human"
_INJECTED_ORIGINS = {
    "task-notification": "task notification",
    "peer": "message from another session",
}
# Claude Code's Write answers "File created successfully at: ..." for a new file and
# "The file ... has been updated successfully" for an existing one (counted on real logs).
UNPARSED_MARKER = "_swe_chat_unparsed"
UNPARSED_SKIP = "line the dataset could not parse"
_CREATED = re.compile(r"^File created successfully at:")
Skips = Counter[str]


def session_logs(repo_dir: Path, home: Path) -> list[Path]:
    """Claude Code's session logs for the repository at `repo_dir`, oldest first.

    Claude Code keeps them under `~/.claude/projects/<directory path with every character that
    is not a letter or digit written as "-">/`. Missing folder: no logs, an empty list.
    """
    # Windows: `home` is %USERPROFILE%, and Claude Code's own uninstall page names
    # %USERPROFILE%/.claude as the folder; the same character rule names the repository folder.
    folder = home / ".claude" / "projects" / project_folder_name(str(repo_dir.resolve()))
    return sorted(folder.glob("*.jsonl"), key=lambda log: log.stat().st_mtime)


def project_folder_name(repo_path: str) -> str:
    """Claude Code's folder name for a repository path: every non-alphanumeric becomes "-"."""
    return re.sub(r"[^A-Za-z0-9]", "-", repo_path)


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield records of the owner's private sessions (never remote safe)."""
    return _read(path, project, PRIVATE_SESSIONS)


def read_swe_chat(path: Path, project: str) -> Iterator[Record]:
    """Yield records of SWE-chat sessions (never remote safe).

    A line holding only `_swe_chat_unparsed`, or valid JSON that is not an object, is the dataset
    exporter's own failure: skipped and counted, the source never had an event there to read.
    """
    return _read(path, project, SWE_CHAT, unparsed_marker=UNPARSED_MARKER)


def read_open_swe_traces(path: Path, project: str) -> Iterator[Record]:
    """Yield records of public Open-SWE-Traces Claude Code rows (remote safe)."""
    return _read(path, project, OPEN_SWE_TRACES)


def _read(
    path: Path, project: str, provenance: Provenance, unparsed_marker: str | None = None
) -> Iterator[Record]:
    """Yield one session's records; each tool result is folded into the action it answers."""
    titles: dict[str, str] = {}
    events = _conversation_events(Path(path), titles, unparsed_marker)
    results = _results_by_call(path, events)
    source = _Source(project, provenance)
    steps: dict[str, int] = {}
    skips: Skips = Counter()
    records: list[Record] = []
    for line_no, event in events:
        try:
            for fields in _event_records(event, results, skips):
                session_id = require_text(event, "sessionId")
                step = steps.get(session_id, 0)
                steps[session_id] = step + 1
                fields["tags"] = (*fields.get("tags", ()), *branch_tags(event))
                records.append(_record(event, source, session_id, step, fields))
        except MalformedError as exc:
            raise ReadError(path, line_no, str(exc)) from exc
    report_skips(path, skips)
    yield from _titled(records, titles)


def _titled(records: list[Record], titles: dict[str, str]) -> list[Record]:
    """Each session's first user turn gains its title tag (see `session_title`).

    Done after the pass because the first typed non-command turn may come after a slash command.
    """
    first_turns: dict[str, int] = {}
    typed: dict[str, str] = {}
    for index, record in enumerate(records):
        if record.kind != Kind.USER_TURN:
            continue
        first_turns.setdefault(record.session_id, index)
        title = fallback_title(record.raw)
        if title:
            typed.setdefault(record.session_id, title)
    for session_id, index in first_turns.items():
        tag = title_tag(session_title(session_id, titles, typed))
        records[index] = replace(records[index], tags=(*records[index].tags, tag))
    return records


def _conversation_events(
    path: Path, titles: dict[str, str], unparsed_marker: str | None
) -> list[tuple[int, dict[str, Any]]]:
    """User and assistant events; metadata events are counted and logged, not dropped silently.

    The session titles `ai-title` events carry are put into `titles`.
    """
    events = []
    skipped: Counter[str] = Counter()
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReadError(path, line_no, f"not valid JSON ({exc.msg})") from exc
            if unparsed_marker and _is_export_artifact(event, unparsed_marker):
                skipped[UNPARSED_SKIP] += 1
                continue
            if not isinstance(event, dict):
                raise ReadError(path, line_no, "a line must hold one event object")
            if _is_metadata(path, line_no, event):
                skipped[event["type"]] += 1
                _keep_title(path, line_no, event, titles)
            else:
                events.append((line_no, event))
    if skipped:
        logger.info("skipped metadata events in %s: %s", path, dict(skipped))
    return events


def _is_export_artifact(line: Any, marker: str) -> bool:
    """True for a SWE-chat line the exporter broke: only the marker key, or not an object at all."""
    return not isinstance(line, dict) or set(line) == {marker}


def _keep_title(path: Path, line_no: int, event: dict[str, Any], titles: dict[str, str]) -> None:
    """Remember a session's title; a malformed `ai-title` event raises ReadError."""
    try:
        if event["type"] == TITLE_EVENT:
            remember_title(event, titles)
    except MalformedError as exc:
        raise ReadError(path, line_no, str(exc)) from exc


def _is_metadata(path: Path, line_no: int, event: dict[str, Any]) -> bool:
    """True for bookkeeping events; an unknown type carrying a message raises ReadError."""
    kind = event.get("type")
    if not isinstance(kind, str):
        message = "missing 'type'" if kind is None else "'type' must be a string"
        raise ReadError(path, line_no, message)
    has_message = event.get("message") is not None
    if kind in _CONVERSATION_TYPES:
        if not has_message:
            raise ReadError(path, line_no, f"{kind!r} event has no 'message'")
        return False
    if has_message and kind not in _REQUEST_LOG_TYPES:
        raise ReadError(path, line_no, f"unknown event type {kind!r}")
    return True


def _results_by_call(
    path: Path, events: list[tuple[int, dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Every tool_result block of the file keyed by its tool_use id."""
    results = {}
    for line_no, event in events:
        try:
            results.update(_event_results(event))
        except MalformedError as exc:
            raise ReadError(path, line_no, str(exc)) from exc
    return results


def _event_results(event: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The tool_result blocks of one event, by tool_use id."""
    return {
        require_text(block, "tool_use_id"): block
        for block in _blocks(event)
        if block.get("type") == "tool_result"
    }


def _blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    """The event's content as blocks; bare text becomes one text block."""
    content = require(require(event, "message"), "content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise MalformedError("message 'content' must be text or a list of blocks")
    return content


@dataclass(frozen=True)
class _Source:
    """What every record of one read shares: project and provenance."""

    project: str
    provenance: Provenance


def _record(
    event: dict[str, Any], source: _Source, session_id: str, step: int, fields: dict[str, Any]
) -> Record:
    """Build a Record from the shared source, the event's timestamp and the shaped fields."""
    return Record(
        harness=HARNESS,
        project=source.project,
        session_id=session_id,
        step=step,
        ts=optional_text(event, "timestamp") or None,
        provenance=source.provenance,
        **fields,
    )


# --- events to record fields ----------------------------------------------------


def _event_records(
    event: dict[str, Any], results: dict[str, dict[str, Any]], skips: Skips
) -> Iterator[dict[str, Any]]:
    """The shaped fields of each record one event yields."""
    optional_text(event, "cwd")
    if event["type"] == "user":
        yield from _user_turns(event, skips)
    else:
        yield from _assistant_records(event, results, skips)


def _user_turns(event: dict[str, Any], skips: Skips) -> Iterator[dict[str, Any]]:
    """The user's text as one turn; events holding only tool results yield nothing."""
    for flag, label in _NOT_TYPED_FLAGS.items():
        if event.get(flag) is True:
            skips[label] += 1  # the harness wrote it, the developer did not: no correction signal
            return
    injected = _injected_label(event)
    if injected is not None:
        skips[injected] += 1  # another process wrote it: quoting it as the developer would be false
        return
    texts = [require_text(b, "text") for b in _blocks(event) if b.get("type") == "text"]
    if not texts:
        return  # tool results only: they are folded into the action they answer
    yield {"kind": Kind.USER_TURN, "raw": "\n".join(texts), "tags": pushback_tags(event)}


def _injected_label(event: dict[str, Any]) -> str | None:
    """Why a user event with a non-human `origin` is skipped; None for human or origin-less ones."""
    kind = origin_kind(event)
    if kind is None or kind == _HUMAN_ORIGIN:
        return None
    return _INJECTED_ORIGINS.get(kind, kind)


def _assistant_records(
    event: dict[str, Any], results: dict[str, dict[str, Any]], skips: Skips
) -> Iterator[dict[str, Any]]:
    """Text, thinking and tool_use blocks as records, each action carrying its result."""
    cwd = optional_text(event, "cwd") or None
    for block in _blocks(event):
        kind = block.get("type")
        if kind == "text":
            yield {"kind": Kind.AGENT_TURN, "raw": require_text(block, "text")}
        elif kind == "tool_use":
            yield from _tool_use(block, results.get(require_text(block, "id")), cwd, skips)
        elif kind != "thinking":
            skips[f"unknown block type {kind}"] += 1


def _tool_use(
    block: dict[str, Any], result: dict[str, Any] | None, cwd: str | None, skips: Skips
) -> Iterator[dict[str, Any]]:
    """The harness's action, then our own text from its result as a separate record."""
    name = require_text(block, "name")
    args = require(block, "input")
    if not isinstance(args, dict):
        raise MalformedError(f"tool input of {name!r} must be an object")
    if name == "Edit" and "old_string" not in args:
        skips["Edit without old_string"] += 1  # no snippet to diff; not a known edit shape
        return
    text = _result_content(result)
    # Our recall answer is ours from the first character.
    own, ours = ("", text) if name in RECALL_TOOL_NAMES else split_our_output(text)
    relative = make_relative(cwd)
    try:
        fields = _action_fields(name, args, relative, own, result)
    except RefusedCallError as exc:
        skips[REFUSED_CALLS] += 1
        fields = {**refused_call(name, args, relative), "raw": own or str(exc)}
    yield fields
    if ours:
        yield {"kind": Kind.TOOL_RESULT, "raw": ours, "tags": (OUR_OUTPUT_RECORD_TAG,)}


def _action_fields(
    name: str,
    args: dict[str, Any],
    relative: Callable[[str], str],
    own: str,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    """The record fields of one tool call; raises RefusedCallError when the tool would reject it."""
    fields = TOOLS.get(name, other_tool)(name, args, relative)
    fields["raw"] = own
    code = _exit_code(fields["kind"], result, own)
    if fields["kind"] == Kind.COMMAND:
        code = exit_code_with_output(str(fields.get("command") or ""), own, code)
    fields["exit_code"] = code
    if name == "Write" and _CREATED.match(own):
        fields["tags"] = (CREATED_TAG,)
    return fields


def _result_content(result: dict[str, Any] | None) -> str:
    """The tool result as text, empty when the call has no result yet."""
    if result is None:
        return ""
    if not isinstance(result.get("is_error", False), bool):
        raise MalformedError("'is_error' must be true or false")
    content = result.get("content")
    if content is None or isinstance(content, str):
        return content or ""
    if isinstance(content, list) and all(isinstance(b, dict) for b in content):
        return "\n".join(optional_text(b, "text") for b in content)
    raise MalformedError("tool_result 'content' must be text or a list of blocks")


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
