"""The common record: the one contract between harness readers and everything after.

Readers turn a harness's logs into `Record`s; the miner, store and learners read
only `Record`s. A record keeps the original text (`raw`) unsummarised, so any
note or recall can quote what actually happened.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import IO, Any


class Kind(StrEnum):
    """What a record is: a turn, an action, or an observation."""

    USER_TURN = "user_turn"
    AGENT_TURN = "agent_turn"
    COMMAND = "command"
    # Reading a file through a harness's file viewer (not a shell command);
    # the loop and blast-radius signals need to know what the agent looked at.
    READ = "read"
    EDIT = "edit"
    TOOL_RESULT = "tool_result"
    REVIEW_COMMENT = "review_comment"
    TEST_RESULT = "test_result"


@dataclass(frozen=True)
class Provenance:
    """Where a record came from.

    `spark_safe` has no default on purpose: a record whose privacy is unknown must
    never be treated as shareable.
    """

    dataset: str
    license: str
    spark_safe: bool


@dataclass(frozen=True, kw_only=True)
class Record:
    """One step of a session, with the original text kept in `raw`."""

    harness: str
    project: str
    session_id: str
    step: int
    kind: Kind
    raw: str
    provenance: Provenance
    ts: str | None = None
    command: str | None = None
    # None means the harness did not report one, never "succeeded".
    exit_code: int | None = None
    files: tuple[str, ...] = ()
    diff: str | None = None
    task_id: str | None = None
    # Source labels kept verbatim in meaning ("correction": SWE-chat pushback), plus
    # "symbiont-output" on text our delivery layer added; the miner must not learn from it.
    tags: tuple[str, ...] = ()
    # For a READ: the (first, last) lines the viewer showed, as the harness
    # gave them (OpenHands uses -1 for "to the end"); None = the whole file
    # or not reported. Paging through a file is not re-reading it.
    line_range: tuple[int, int] | None = None


class RecordFormatError(ValueError):
    """A JSONL line that is not a valid record; names the line number."""

    def __init__(self, line_no: int, reason: str):
        """Keep the line number and reason for callers to report."""
        super().__init__(f"line {line_no}: {reason}")
        self.line_no = line_no
        self.reason = reason


def dump_jsonl(records: Iterable[Record], fh: IO[str]) -> None:
    """Write one JSON object per record to an open text file."""
    for record in records:
        fh.write(json.dumps(asdict(record)) + "\n")


def load_jsonl(fh: IO[str]) -> Iterator[Record]:
    """Read records back; a bad line raises RecordFormatError with its number."""
    for line_no, line in enumerate(fh, start=1):
        try:
            yield _record_from_dict(json.loads(line))
        except (ValueError, KeyError, TypeError) as exc:
            raise RecordFormatError(line_no, _describe(exc)) from exc


def _describe(exc: Exception) -> str:
    """A readable reason for a bad record: names a missing field."""
    if isinstance(exc, KeyError):
        return f"missing field {exc.args[0]!r}"
    return str(exc)


def _record_from_dict(data: dict[str, Any]) -> Record:
    """Rebuild a Record from its JSON dict; wrong types raise."""
    fields = dict(data)
    fields["kind"] = Kind(data["kind"])
    fields["files"] = tuple(data["files"])
    fields["tags"] = tuple(data.get("tags", ()))
    line_range = data.get("line_range")
    fields["line_range"] = None if line_range is None else _line_range(line_range)
    fields["provenance"] = _provenance_from_dict(data["provenance"])
    return Record(**fields)


def _line_range(value: Any) -> tuple[int, int]:
    """The (first, last) pair from JSON; anything else raises TypeError."""
    if not (isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value)):
        raise TypeError(f"line_range must be two integers, got {value!r}")
    return (value[0], value[1])


def _provenance_from_dict(data: dict[str, Any]) -> Provenance:
    """Provenance from JSON; spark_safe must be an actual boolean."""
    spark_safe = data["spark_safe"]
    if not isinstance(spark_safe, bool):
        raise TypeError(f"spark_safe must be true or false, got {spark_safe!r}")
    return Provenance(dataset=data["dataset"], license=data["license"], spark_safe=spark_safe)
