"""Reader for mini-SWE-agent trajectories.

Input is JSONL, one trajectory per line: `trajectory_id`, `instance_id` and
`messages`, the chat in mini-SWE-agent's own format. An assistant message holds
reasoning plus exactly one fenced bash block; the next user message is the
observation (`<returncode>N</returncode><output>...</output>`). Rows are Open-SWE-Traces
`minisweagent` rows unless they carry `"source": "local-run"`, which marks our
own runs on public benchmark repos.

Each command becomes one record carrying its observation as `raw`. A command
that writes a file through sed -i, a redirect, a heredoc or tee is an edit.
Anything our delivery layer appended to an observation is cut off and tagged.
"""

import json
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG, split_our_output
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "mini-swe-agent"
OPEN_SWE_TRACES = Provenance(dataset="open-swe-traces", license="see-dataset-card", spark_safe=True)
# Our own Glimmer runs use public benchmark repos only, so they may reach Spark.
LOCAL_RUN = Provenance(dataset="local-run", license="own-output", spark_safe=True)
_SOURCES = {None: OPEN_SWE_TRACES, "local-run": LOCAL_RUN}

_BASH_BLOCK = re.compile(r"```bash[ \t]*\n(.*?)\n?```", re.DOTALL)
_RETURN_CODE = re.compile(r"<returncode>\s*(-?\d+)\s*</returncode>")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_WORKSPACE_PREFIXES = ("/testbed/", "./")
_OPERATORS = {"&&", "||", ";", "|", "&", "(", ")"}


class _MalformedError(Exception):
    """Internal: a row is not in the shape this reader knows. Becomes a ReadError."""


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield the records of a mini-SWE-agent trajectory file; a bad line raises ReadError."""
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                records = _session_records(json.loads(line), project)
            except json.JSONDecodeError as exc:
                raise ReadError(path, line_no, f"not valid JSON ({exc.msg})") from exc
            except _MalformedError as exc:
                raise ReadError(path, line_no, str(exc)) from exc
            yield from records


@dataclass
class _Session:
    project: str
    session_id: str
    task_id: str
    provenance: Provenance
    records: list[Record] = field(default_factory=list)

    def add(self, kind: Kind, raw: str, ours: str = "", **fields: Any) -> None:
        self.records.append(
            Record(
                harness=HARNESS,
                project=self.project,
                session_id=self.session_id,
                step=len(self.records),
                kind=kind,
                raw=raw,
                task_id=self.task_id,
                provenance=self.provenance,
                tags=(OUR_OUTPUT_RECORD_TAG,) if ours else (),
                **fields,
            )
        )


def _session_records(row: Any, project: str) -> list[Record]:
    if not isinstance(row, dict):
        raise _MalformedError("a line must hold one trajectory object")
    messages = _require(row, "messages")
    if not isinstance(messages, list):
        raise _MalformedError("'messages' must be a list")
    session = _Session(
        project=project,
        session_id=_require(row, "trajectory_id"),
        task_id=_require(row, "instance_id"),
        provenance=_provenance(row.get("source")),
    )
    _add_messages(session, messages)
    return session.records


def _provenance(source: Any) -> Provenance:
    if source not in _SOURCES:
        raise _MalformedError(f"unknown source {source!r} (known: local-run, or none)")
    return _SOURCES[source]


def _require(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict) or mapping.get(key) is None:
        raise _MalformedError(f"missing {key!r}")
    return mapping[key]


def _text(message: Any) -> str:
    content = _require(message, "content")
    if not isinstance(content, str):
        raise _MalformedError("message 'content' must be a string")
    return content


def _add_messages(session: _Session, messages: list[Any]) -> None:
    index = 0
    seen_task = False
    while index < len(messages):
        message = messages[index]
        role = _require(message, "role")
        index += 1
        if role == "system":
            continue
        if role == "user":
            if seen_task:
                _add_stray_observation(session, _text(message))
            else:
                session.add(Kind.USER_TURN, _text(message))
            seen_task = True
        elif role == "assistant":
            observation = None
            if index < len(messages) and messages[index].get("role") == "user":
                observation = _text(messages[index])
                index += 1
            _add_assistant_message(session, _text(message), observation)
        else:
            raise _MalformedError(f"unknown message role {role!r}")


def _add_stray_observation(session: _Session, text: str) -> None:
    # An observation with no command before it, e.g. the harness's format-error notice.
    own, ours = split_our_output(text)
    session.add(Kind.TOOL_RESULT, own, ours)


def _add_assistant_message(session: _Session, text: str, observation: str | None) -> None:
    blocks = _BASH_BLOCK.findall(text)
    if len(blocks) > 1:
        raise _MalformedError(f"{len(blocks)} bash blocks in one message; expected one action")
    if not blocks:
        session.add(Kind.AGENT_TURN, text)
        return
    thought = _BASH_BLOCK.sub("", text).strip()
    if thought:
        session.add(Kind.AGENT_TURN, thought)
    own, ours = split_our_output(observation or "")
    command = blocks[0].strip()
    files = _written_files(command)
    session.add(
        Kind.EDIT if files else Kind.COMMAND,
        own,
        ours,
        command=command,
        files=files,
        exit_code=_exit_code(observation and own),
    )


def _exit_code(observation: str | None) -> int | None:
    """None when there is no observation or no return code: unknown, not success."""
    found = _RETURN_CODE.search(observation or "")
    return int(found.group(1)) if found else None


# --- which files a command writes -------------------------------------------------


def _written_files(command: str) -> tuple[str, ...]:
    tokens = _tokens(_without_heredoc_bodies(command))
    files: list[str] = []
    for segment in _segments(tokens):
        files.extend(_segment_writes(segment))
    return tuple(dict.fromkeys(_repo_relative(f) for f in files))


def _without_heredoc_bodies(command: str) -> str:
    kept: list[str] = []
    terminator = None
    for line in command.splitlines():
        if terminator is not None:
            terminator = None if line.strip() == terminator else terminator
            continue
        kept.append(line)
        opened = _HEREDOC.search(line)
        terminator = opened.group(2) if opened else None
    return " ; ".join(kept)


def _tokens(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quoting: no file can be named reliably; the command stays a command.
        return []


def _segments(tokens: list[str]) -> Iterator[list[str]]:
    current: list[str] = []
    for token in tokens:
        if token in _OPERATORS:
            yield current
            current = []
        else:
            current.append(token)
    yield current


def _segment_writes(segment: list[str]) -> list[str]:
    files = _redirect_targets(segment)
    if segment[:1] == ["sed"] and any(_is_in_place(t) for t in segment):
        files += _sed_files(segment)
    if segment[:1] == ["tee"]:
        files += [t for t in segment[1:] if not t.startswith("-") and t not in _REDIRECTS]
    return files


_REDIRECTS = {">", ">>", "<", "<<", "<<<"}


def _redirect_targets(segment: list[str]) -> list[str]:
    targets = []
    for token, target in zip(segment, segment[1:], strict=False):
        if token in (">", ">>") and not target.startswith("/dev/"):
            targets.append(target)
    return targets


def _is_in_place(token: str) -> bool:
    return token == "--in-place" or (token.startswith("-i") and not token.startswith("--"))


def _sed_files(segment: list[str]) -> list[str]:
    positional: list[str] = []
    script_given = False
    skip_next = False
    for token in segment[1:]:
        if skip_next:
            skip_next = False
        elif token in ("-e", "-f"):
            script_given = skip_next = True
        elif not token.startswith("-") and token not in _REDIRECTS:
            positional.append(token)
    # Without -e/-f the first positional argument is the script, not a file.
    return positional if script_given else positional[1:]


def _repo_relative(path: str) -> str:
    for prefix in _WORKSPACE_PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path
