"""Reader for mini-SWE-agent trajectories (JSONL, one trajectory per line).

Each fenced bash command becomes one record carrying its observation as `raw`;
a command that writes a file is an edit. `read` is never spark safe;
`read_local_run` refuses any task that is not a public benchmark id. Text our
delivery layer appended to an observation becomes its own tagged tool result.
"""

import json
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.holdout import UnrecognisedTaskIdError, normalise_task_id
from symbiont.records.ours import OUR_OUTPUT_RECORD_TAG, split_our_output
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "mini-swe-agent"
UNLABELED = Provenance(dataset="mini-swe-agent-unlabeled", license="unknown", spark_safe=False)
OPEN_SWE_TRACES = Provenance(dataset="open-swe-traces", license="see-dataset-card", spark_safe=True)
# Our own Glimmer runs use public benchmark repos only, so they may reach Spark.
LOCAL_RUN = Provenance(dataset="local-run", license="own-output", spark_safe=True)

# Repos of the public benchmark tasks our Glimmer runs may use; a run on any other repo
# could hold private code and must not be labeled spark safe.
PUBLIC_BENCHMARK_REPOS = frozenset({"tobymao/sqlglot"})

_BASH_BLOCK = re.compile(r"```bash[ \t]*\n(.*?)\n?```", re.DOTALL)
_RETURN_CODE = re.compile(r"<returncode>\s*(-?\d+)\s*</returncode>")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_WORKSPACE_PREFIXES = ("/testbed/", "./")
_OPERATORS = {"&&", "||", ";", "|", "&", "(", ")"}


class _MalformedError(Exception):
    """Internal: a row is not in the shape this reader knows. Becomes a ReadError."""


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield records of a trajectory file of unlabeled origin (never spark safe)."""
    return _read(path, project, UNLABELED, public_tasks_only=False)


def read_open_swe_traces(path: Path, project: str) -> Iterator[Record]:
    """Yield records of public Open-SWE-Traces `minisweagent` rows (spark safe)."""
    return _read(path, project, OPEN_SWE_TRACES, public_tasks_only=False)


def read_local_run(path: Path, project: str) -> Iterator[Record]:
    """Yield records of our own runs; raises unless every task is on a public benchmark repo.

    It trusts the row's declared `instance_id`; only our own runner writes these files.
    """
    return _read(path, project, LOCAL_RUN, public_tasks_only=True)


def _read(
    path: Path, project: str, provenance: Provenance, *, public_tasks_only: bool
) -> Iterator[Record]:
    """Yield each trajectory's records; a bad line raises ReadError naming file and line."""
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                records = _session_records(
                    json.loads(line), project, provenance, public_tasks_only=public_tasks_only
                )
            except json.JSONDecodeError as exc:
                raise ReadError(path, line_no, f"not valid JSON ({exc.msg})") from exc
            except _MalformedError as exc:
                raise ReadError(path, line_no, str(exc)) from exc
            yield from records


@dataclass
class _Session:
    """The records of one trajectory being built."""

    project: str
    session_id: str
    task_id: str
    provenance: Provenance
    records: list[Record] = field(default_factory=list)

    def add(self, kind: Kind, raw: str, **fields: Any) -> None:
        """Append a record of the given kind with the session's shared fields."""
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
                **fields,
            )
        )

    def add_ours(self, ours: str) -> None:
        """Keep text our delivery layer appended as its own tagged tool result."""
        if ours:
            self.add(Kind.TOOL_RESULT, ours, tags=(OUR_OUTPUT_RECORD_TAG,))


def _session_records(
    row: Any, project: str, provenance: Provenance, *, public_tasks_only: bool
) -> list[Record]:
    """All records of one trajectory row."""
    if not isinstance(row, dict):
        raise _MalformedError("a line must hold one trajectory object")
    messages = _require(row, "messages")
    if not isinstance(messages, list):
        raise _MalformedError("'messages' must be a list")
    session = _Session(
        project=project,
        session_id=_require_text(row, "trajectory_id"),
        task_id=_require_text(row, "instance_id"),
        provenance=provenance,
    )
    if public_tasks_only:
        _require_public_task(session.task_id)
    _add_messages(session, messages)
    return session.records


def _require_public_task(task_id: str) -> None:
    """Raise unless a local run's task is a public benchmark id."""
    try:
        repo = normalise_task_id(task_id).split("#")[0]
    except UnrecognisedTaskIdError as exc:
        raise _MalformedError(f"a local run must be on a public benchmark task: {exc}") from exc
    if repo not in PUBLIC_BENCHMARK_REPOS:
        raise _MalformedError(
            f"a local run must be on a public benchmark repo; {repo!r} is not in "
            f"{sorted(PUBLIC_BENCHMARK_REPOS)}"
        )


def _require(mapping: Any, key: str) -> Any:
    """The mapping's value for `key`; a missing or null one raises _MalformedError."""
    if not isinstance(mapping, dict) or mapping.get(key) is None:
        raise _MalformedError(f"missing {key!r}")
    return mapping[key]


def _require_str(value: Any, field: str) -> str:
    """The value if it is a string, else _MalformedError naming the field."""
    if not isinstance(value, str):
        raise _MalformedError(f"{field!r} must be a string, got {type(value).__name__}")
    return value


def _require_text(mapping: Any, key: str) -> str:
    """The string under `key` in the mapping; missing or non-string raises _MalformedError."""
    return _require_str(_require(mapping, key), key)


def _text(message: Any) -> str:
    """A message's content, which must be a string."""
    content = _require(message, "content")
    if not isinstance(content, str):
        raise _MalformedError("message 'content' must be a string")
    return content


def _add_messages(session: _Session, messages: list[Any]) -> None:
    """Walk the chat, pairing each command with the observation that answers it."""
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
            index += _add_assistant_message(session, _text(message), messages[index : index + 1])
        else:
            raise _MalformedError(f"unknown message role {role!r}")


def _add_stray_observation(session: _Session, text: str) -> None:
    """Keep an observation with no command before it (e.g. a format-error notice) as a result."""
    own, ours = split_our_output(text)
    session.add(Kind.TOOL_RESULT, own)
    session.add_ours(ours)


def _add_assistant_message(session: _Session, text: str, following: list[Any]) -> int:
    """Add the records of one assistant message; return how many following messages it used."""
    blocks = _BASH_BLOCK.findall(text)
    if len(blocks) != 1:
        # A format error: the next message is the harness's notice, read as a stray observation.
        session.add(Kind.AGENT_TURN, text)
        return 0
    observation = _answering_observation(following)
    thought = _BASH_BLOCK.sub("", text).strip()
    if thought:
        session.add(Kind.AGENT_TURN, thought)
    own, ours = split_our_output(observation or "")
    command = blocks[0].strip()
    files = _written_files(command)
    session.add(
        Kind.EDIT if files else Kind.COMMAND,
        own,
        command=command,
        files=files,
        exit_code=None if observation is None else _exit_code(own),
    )
    session.add_ours(ours)
    return 0 if observation is None else 1


def _answering_observation(following: list[Any]) -> str | None:
    """The observation text if the next message is the user's answer, else None."""
    if not following:
        return None
    message = following[0]
    if not isinstance(message, dict):
        raise _MalformedError("a message after an assistant message must be an object")
    return _text(message) if message.get("role") == "user" else None


def _exit_code(observation: str) -> int | None:
    """None when there is no observation or no return code: unknown, not success."""
    found = _RETURN_CODE.search(observation)
    return int(found.group(1)) if found else None


# --- which files a command writes -------------------------------------------------


def _written_files(command: str) -> tuple[str, ...]:
    """Files a shell command writes via sed -i, a redirect, a heredoc or tee."""
    tokens = _tokens(_without_heredoc_bodies(command))
    files: list[str] = []
    for segment in _segments(tokens):
        files.extend(_segment_writes(segment))
    return tuple(dict.fromkeys(_repo_relative(f) for f in files))


def _without_heredoc_bodies(command: str) -> str:
    """The command without heredoc bodies, whose text is not shell."""
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
    """Shell tokens with operators split out; unbalanced quoting gives none."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quoting: no file can be named reliably; the command stays a command.
        return []


def _segments(tokens: list[str]) -> Iterator[list[str]]:
    """The command split at shell operators."""
    current: list[str] = []
    for token in tokens:
        if token in _OPERATORS:
            yield current
            current = []
        else:
            current.append(token)
    yield current


def _segment_writes(segment: list[str]) -> list[str]:
    """Files one command segment writes to."""
    files = _redirect_targets(segment)
    if segment[:1] == ["sed"] and any(_is_in_place(t) for t in segment):
        files += _sed_files(segment)
    if segment[:1] == ["tee"]:
        files += [t for t in segment[1:] if not t.startswith("-") and t not in _REDIRECTS]
    return files


_REDIRECTS = {">", ">>", "<", "<<", "<<<"}


def _redirect_targets(segment: list[str]) -> list[str]:
    """Targets of > and >>, ignoring /dev/ paths."""
    targets = []
    for token, target in zip(segment, segment[1:], strict=False):
        if token in (">", ">>") and not target.startswith("/dev/"):
            targets.append(target)
    return targets


def _is_in_place(token: str) -> bool:
    """True for sed's -i and --in-place flags."""
    return token == "--in-place" or (token.startswith("-i") and not token.startswith("--"))


def _sed_files(segment: list[str]) -> list[str]:
    """The file arguments of a sed call, after its script."""
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
    """The path without the benchmark workspace prefix."""
    for prefix in _WORKSPACE_PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path
