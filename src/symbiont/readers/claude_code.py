"""Reader for Claude Code session logs (JSONL, one event per line).

A tool result travels in the `raw` of the action it answers; SWE-chat's `prompt_pushback`
becomes the "correction" tag. Unmineable content (metadata events, unknown block types,
harness-written user turns) is skipped, counted and logged; malformed shapes raise ReadError.
`read` is for private sessions: unknown privacy is never shareable.
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.readers.claude_code_fields import (
    MalformedError,
    optional_text,
    require,
    require_text,
)
from symbiont.readers.claude_code_tags import TITLE_EVENT, EventTags, remember_title
from symbiont.readers.claude_code_tools import TOOLS, make_relative, other_tool
from symbiont.readers.errors import ReadError
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG, RECALL_TOOL_NAMES, split_our_output
from symbiont.records.output_failure import exit_code_with_output
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "claude-code"
PRIVATE_SESSIONS = Provenance(dataset="private-sessions", license="none", spark_safe=False)
SWE_CHAT = Provenance(dataset="swe-chat", license="see-dataset-card", spark_safe=False)
OPEN_SWE_TRACES = Provenance(dataset="open-swe-traces", license="see-dataset-card", spark_safe=True)

CORRECTION = "correction"
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
    """Yield records of the owner's private sessions (never spark safe)."""
    return _read(path, project, PRIVATE_SESSIONS)


def read_swe_chat(path: Path, project: str) -> Iterator[Record]:
    """Yield records of SWE-chat sessions (never spark safe)."""
    return _read(path, project, SWE_CHAT)


def read_open_swe_traces(path: Path, project: str) -> Iterator[Record]:
    """Yield records of public Open-SWE-Traces Claude Code rows (spark safe)."""
    return _read(path, project, OPEN_SWE_TRACES)


def _read(path: Path, project: str, provenance: Provenance) -> Iterator[Record]:
    """Yield one session's records; each tool result is folded into the action it answers."""
    titles: dict[str, str] = {}
    events = _conversation_events(Path(path), titles)
    tagger = EventTags(titles)
    results = _results_by_call(path, events)
    source = _Source(project, provenance)
    steps: dict[str, int] = {}
    skips: Skips = Counter()
    for line_no, event in events:
        try:
            for fields in _event_records(event, results, skips):
                session_id = require_text(event, "sessionId")
                step = steps.get(session_id, 0)
                steps[session_id] = step + 1
                first_turn = fields["kind"] == Kind.USER_TURN
                fields["tags"] = (
                    *fields.get("tags", ()),
                    *tagger.of(event, session_id, first_user_turn=first_turn),
                )
                yield _record(event, source, session_id, step, fields)
        except MalformedError as exc:
            raise ReadError(path, line_no, str(exc)) from exc
    if skips:
        logger.warning("skipped content in %s: %s", path, dict(skips))


def _conversation_events(path: Path, titles: dict[str, str]) -> list[tuple[int, dict[str, Any]]]:
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
    texts = [require_text(b, "text") for b in _blocks(event) if b.get("type") == "text"]
    if not texts:
        return  # tool results only: they are folded into the action they answer
    yield {"kind": Kind.USER_TURN, "raw": "\n".join(texts), "tags": _pushback_tags(event)}


def _pushback_tags(event: dict[str, Any]) -> tuple[str, ...]:
    """`correction` when SWE-chat marked the turn as pushback; any other flag value raises."""
    flag = event.get("prompt_pushback")
    if flag is None or flag is False or flag == "":
        return ()
    if flag is True or isinstance(flag, str):
        return (CORRECTION,)
    raise MalformedError(f"prompt_pushback must be true/false or a label, got {flag!r}")


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
    fields = TOOLS.get(name, other_tool)(name, args, make_relative(cwd))
    fields["raw"] = own
    code = _exit_code(fields["kind"], result, own)
    if fields["kind"] == Kind.COMMAND:
        code = exit_code_with_output(str(fields.get("command") or ""), own, code)
    fields["exit_code"] = code
    yield fields
    if ours:
        yield {"kind": Kind.TOOL_RESULT, "raw": ours, "tags": (OUR_OUTPUT_RECORD_TAG,)}


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
