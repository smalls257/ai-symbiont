"""Reader for OpenHands trajectories as published in nebius/SWE-rebench-openhands-trajectories.

Input is JSONL, one dataset row per line: `trajectory_id`, `instance_id` and
`trajectory`, a list of chat messages (system prompt, user issue, assistant
turns with `tool_calls`, and `tool` observations answering them by
`tool_call_id`). Tool-call `arguments` are a JSON string in the published data,
or a decoded object if the dataset card's helper was applied; both are read.

Each assistant action becomes one record and carries its observation as `raw`,
so a failed command and its error text travel together. Paths are made
relative to the task's workspace (`<uploaded_files>` in the issue) so the same
file matches across sessions; command text is kept verbatim.
"""

import difflib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "openhands"
PROVENANCE = Provenance(
    dataset="nebius/SWE-rebench-openhands-trajectories",
    license="CC-BY-4.0",
    spark_safe=True,
)

_WORKSPACE = re.compile(r"<uploaded_files>\s*(\S+?)/?\s*</uploaded_files>")
# OpenHands appends both markers to every finished command; -1 means it timed out.
_EXIT_CODE = re.compile(
    r"\[(?:Command finished with exit code|The command completed with exit code) (-?\d+)\.?\]"
)
# The file editor reports a rejected edit or view (old_str not found, bad path)
# as an observation starting with this marker instead of an exit code.
_EDITOR_ERROR = "ERROR:"


class _MalformedError(Exception):
    """Internal: a row is not in the shape this reader knows. Becomes a ReadError."""


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield the records of an OpenHands trajectory file; a bad line raises ReadError."""
    for row in read_each_row(path, project):
        if isinstance(row, ReadError):
            raise row
        yield from row


def read_each_row(path: Path, project: str) -> Iterator[list[Record] | ReadError]:
    """One item per line: that row's records, or the ReadError naming the line.

    For a caller with a pre-registered rule for rows the reader refuses (it must count and
    report them); `read` raises on the first one instead.
    """
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                yield _session_records(json.loads(line), project)
            except json.JSONDecodeError as exc:
                yield ReadError(path, line_no, f"not valid JSON ({exc.msg})")
            except _MalformedError as exc:
                yield ReadError(path, line_no, str(exc))


@dataclass
class _Session:
    project: str
    session_id: str
    task_id: str
    workspace: str | None
    records: list[Record] = field(default_factory=list)

    def add(self, kind: Kind, raw: str, **fields: Any) -> None:
        self.records.append(
            Record(
                harness=HARNESS,
                project=self.project,
                session_id=self.session_id,
                step=len(self.records),
                kind=kind,
                raw=raw,
                task_id=self.task_id,
                provenance=PROVENANCE,
                **fields,
            )
        )

    def repo_path(self, path: str) -> str:
        if self.workspace and path.rstrip("/") == self.workspace:
            return "."
        if self.workspace and path.startswith(self.workspace + "/"):
            return path[len(self.workspace) + 1 :]
        return path


def _session_records(row: Any, project: str) -> list[Record]:
    if not isinstance(row, dict):
        raise _MalformedError("a line must hold one trajectory object")
    messages = _require(row, "trajectory")
    if not isinstance(messages, list):
        raise _MalformedError("'trajectory' must be a list of messages")
    session = _Session(
        project=project,
        session_id=_require(row, "trajectory_id"),
        task_id=_require(row, "instance_id"),
        workspace=_workspace_root(messages),
    )
    observations = _observations_by_call(messages)
    for message in messages:
        _add_message(session, message, observations)
    return session.records


def _require(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict) or mapping.get(key) is None:
        raise _MalformedError(f"missing {key!r}")
    return mapping[key]


def _workspace_root(messages: list[dict[str, Any]]) -> str | None:
    for message in messages:
        if message.get("role") == "user":
            found = _WORKSPACE.search(message.get("content") or "")
            return found.group(1) if found else None
    return None


def _observations_by_call(messages: list[dict[str, Any]]) -> dict[str, str]:
    call_ids = {call.get("id") for message in messages for call in message.get("tool_calls") or []}
    observations = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        call_id = _require(message, "tool_call_id")
        if call_id not in call_ids:
            raise _MalformedError(f"observation answers unknown tool call {call_id!r}")
        observations[call_id] = message.get("content") or ""
    return observations


def _add_message(session: _Session, message: dict[str, Any], observations: dict[str, str]) -> None:
    role = _require(message, "role")
    if role in ("system", "tool"):
        # The system prompt is the harness's fixed preamble, the same in every
        # session; tool observations are folded into the action they answer.
        return
    if role == "user":
        session.add(Kind.USER_TURN, message.get("content") or "")
    elif role == "assistant":
        _add_assistant_turn(session, message, observations)
    else:
        raise _MalformedError(f"unknown message role {role!r}")


def _add_assistant_turn(
    session: _Session, message: dict[str, Any], observations: dict[str, str]
) -> None:
    text = message.get("content") or ""
    if text.strip():
        session.add(Kind.AGENT_TURN, text)
    for call in message.get("tool_calls") or []:
        function = _require(call, "function")
        name = _require(function, "name")
        action = _ACTIONS.get(name)
        if action is None:
            raise _MalformedError(
                f"unknown tool {name!r} (known: {', '.join(sorted(_ACTIONS))}); "
                "a different OpenHands version?"
            )
        action(session, _arguments(function), observations.get(call.get("id")))


def _arguments(function: dict[str, Any]) -> dict[str, Any]:
    arguments = _require(function, "arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise _MalformedError(f"tool arguments are not valid JSON ({exc.msg})") from exc
    if not isinstance(arguments, dict):
        raise _MalformedError("tool arguments must be an object")
    return arguments


# --- actions -----------------------------------------------------------------


def _add_bash(session: _Session, args: dict[str, Any], observation: str | None) -> None:
    session.add(
        Kind.COMMAND,
        observation or "",
        command=_require(args, "command"),
        exit_code=_bash_exit_code(observation),
    )


def _bash_exit_code(observation: str | None) -> int | None:
    """None when the run has no observation or no exit marker: unknown, not success."""
    codes = _EXIT_CODE.findall(observation or "")
    return int(codes[-1]) if codes else None


def _add_file_editor_action(
    session: _Session, args: dict[str, Any], observation: str | None
) -> None:
    command = _require(args, "command")
    path = session.repo_path(_require(args, "path"))
    exit_code = _editor_exit_code(observation)
    if command == "view":
        session.add(
            Kind.READ,
            observation or "",
            files=(path,),
            exit_code=exit_code,
            line_range=_view_range(args),
        )
        return
    make_diff = _EDIT_DIFFS.get(command)
    if make_diff is None:
        raise _MalformedError(f"unknown str_replace_editor command {command!r}")
    session.add(
        Kind.EDIT,
        observation or "",
        files=(path,),
        diff=make_diff(path, args),
        exit_code=exit_code,
    )


def _view_range(args: dict[str, Any]) -> tuple[int, int] | None:
    """The lines a view showed, as OpenHands gave them (-1 = to the end)."""
    value = args.get("view_range")
    if value is None:
        return None
    if not (isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value)):
        raise _MalformedError(f"view_range must be two line numbers, got {value!r}")
    return (value[0], value[1])


def _editor_exit_code(observation: str | None) -> int | None:
    if observation is None:
        return None
    return 1 if observation.startswith(_EDITOR_ERROR) else 0


def _add_thought(session: _Session, args: dict[str, Any], observation: str | None) -> None:
    session.add(Kind.AGENT_TURN, _require(args, "thought"))


def _add_finish(session: _Session, args: dict[str, Any], observation: str | None) -> None:
    session.add(Kind.AGENT_TURN, _require(args, "message"))


def _add_task_plan(session: _Session, args: dict[str, Any], observation: str | None) -> None:
    session.add(Kind.AGENT_TURN, json.dumps(args, ensure_ascii=False))


_ACTIONS: dict[str, Callable[[_Session, dict[str, Any], str | None], None]] = {
    "execute_bash": _add_bash,
    "str_replace_editor": _add_file_editor_action,
    "think": _add_thought,
    "finish": _add_finish,
    "task_tracker": _add_task_plan,
}


# --- diffs ---------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    return [line + "\n" for line in text.splitlines()]


def _replace_diff(path: str, args: dict[str, Any]) -> str:
    """Diff `old_str` against `new_str` for a replace.

    OpenHands does not record where `old_str` sits in the file, so hunk line
    numbers are relative to the replaced snippet, not the file.
    """
    # An omitted new_str is the editor's documented way to delete old_str.
    new = args.get("new_str") or ""
    diff = difflib.unified_diff(
        _lines(_require(args, "old_str")), _lines(new), f"a/{path}", f"b/{path}"
    )
    return "".join(diff)


def _create_diff(path: str, args: dict[str, Any]) -> str:
    diff = difflib.unified_diff([], _lines(_require(args, "file_text")), "/dev/null", f"b/{path}")
    return "".join(diff)


def _insert_diff(path: str, args: dict[str, Any]) -> str:
    after = int(_require(args, "insert_line"))
    added = _lines(_require(args, "new_str"))
    header = f"--- a/{path}\n+++ b/{path}\n@@ -{after},0 +{after + 1},{len(added)} @@\n"
    return header + "".join("+" + line for line in added)


def _undo_diff(path: str, args: dict[str, Any]) -> None:
    """The editor restores the previous version without saying what it was."""
    return


_EDIT_DIFFS: dict[str, Callable[[str, dict[str, Any]], str | None]] = {
    "str_replace": _replace_diff,
    "create": _create_diff,
    "insert": _insert_diff,
    "undo_edit": _undo_diff,
}
