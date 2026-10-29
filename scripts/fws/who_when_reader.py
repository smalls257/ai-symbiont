"""Reader for Who&When (Kevin355/Who_and_When): multi-agent failures blamed on one agent and step.

Algorithm-Generated is AG2 CaptainAgent (agent in `name`), Hand-Crafted is Magentic-One (agent in
`role`, e.g. "Orchestrator (thought)"). Each message is one record; `mistake_step` is the 0-based
message index. Terminal output is a COMMAND with the exit code it printed. Questions come from
GAIA and AssistantBench, whose terms forbid resharing: text stays in memory, only counts leave.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from annotated import AnnotatedTrace, TaskKind

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind, Provenance, Record

SOURCE = "who_and_when"
HARNESS = "multi-agent"
PROVENANCE = Provenance(
    dataset="Kevin355/Who_and_When",
    license="MIT (GitHub repository); GAIA and AssistantBench questions, local use only",
    spark_safe=False,
)
# Parquet file and the agent framework that produced its logs (arXiv 2505.00212, section 3).
SPLITS = {
    "algorithm_generated": ("Algorithm-Generated.parquet", "AG2 CaptainAgent"),
    "hand_crafted": ("Hand-Crafted.parquet", "Magentic-One"),
}
_TERMINALS = frozenset({"computer_terminal", "computerterminal"})
_HUMAN = "human"
_EXIT_CODE = re.compile(r"exitcode: ?(-?\d+)")
_FENCE = re.compile(r"```(\w+)")
_PROGRAM_OF_FENCE = {"py": "python", "python": "python", "sh": "bash", "bash": "bash"}


@dataclass(frozen=True)
class BlameCheck:
    """Whether the blamed agent wrote the blamed message: a check on the 0-based reading."""

    trace: AnnotatedTrace
    agent_matches: bool | None


def read_who_when(root: Path) -> list[BlameCheck]:
    """Every row of both parquet files; raises ReadError naming the file and row at fault."""
    checks: list[BlameCheck] = []
    for split, (name, _) in SPLITS.items():
        path = root / name
        rows = _rows(path)
        checks += [_checked_row(path, number, row, split) for number, row in enumerate(rows, 1)]
        ids = [check.trace.records[0].session_id for check in checks if check.trace.split == split]
        if len(set(ids)) != len(ids):
            raise ReadError(path, 0, "a question id repeats, sessions would merge")
    return checks


def _checked_row(path: Path, number: int, row: dict[str, Any], split: str) -> BlameCheck:
    """One row as trace_from_row reads it; a malformed row raises ReadError (row `number`)."""
    try:
        return trace_from_row(row, split)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ReadError(path, number, f"not a Who&When row: {exc!r}") from exc


def _rows(path: Path) -> list[dict[str, Any]]:
    """The parquet rows as dicts; raises FileNotFoundError naming a missing file."""
    if not path.is_file():
        raise FileNotFoundError(path)
    relation = duckdb.sql("select * from read_parquet(?)", params=[str(path)])
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def trace_from_row(row: dict[str, Any], split: str) -> BlameCheck:
    """One row as an AnnotatedTrace; a blamed step outside the history is counted as unplaced."""
    history = row["history"]
    session = f"{SOURCE}:{split}:{row['question_ID']}"
    records = [_message_record(history, n, session, split) for n in range(len(history))]
    blamed = int(row["mistake_step"])
    placed = 0 <= blamed < len(history)
    trace = AnnotatedTrace(
        source=SOURCE,
        split=split,
        framework=SPLITS[split][1],
        task_kind=TaskKind.WEB_QA,
        records=tuple(records),
        error_steps=(blamed,) if placed else (),
        unplaced_errors=0 if placed else 1,
    )
    matches = _agent(history[blamed]) == _canonical(row["mistake_agent"]) if placed else None
    return BlameCheck(trace, matches)


def _agent(message: dict[str, Any]) -> str:
    """The speaking agent: AG2's `name`, else Magentic-One's role without its "(...)" suffix."""
    return _canonical(message.get("name") or message["role"])


def _canonical(agent: str) -> str:
    """Lowercase, no role suffix, so "WebSurfer" and "Websurfer" are the same agent."""
    return agent.split(" (")[0].strip().lower()


def _message_record(
    history: Sequence[dict[str, Any]], index: int, session: str, split: str
) -> Record:
    """Message `index` as a record: terminal output is a COMMAND, the human a USER_TURN."""
    agent, text = _agent(history[index]), history[index]["content"] or ""
    kind = Kind.AGENT_TURN
    if agent in _TERMINALS:
        kind = Kind.COMMAND
    elif agent == _HUMAN:
        kind = Kind.USER_TURN
    exit_code = _EXIT_CODE.search(text) if kind == Kind.COMMAND else None
    return Record(
        harness=HARNESS,
        project=f"{SOURCE}:{split}",
        session_id=session,
        step=index,
        kind=kind,
        raw=text,
        provenance=PROVENANCE,
        command=_program_run(history, index) if kind == Kind.COMMAND else None,
        exit_code=int(exit_code.group(1)) if exit_code else None,
    )


def _program_run(history: Sequence[dict[str, Any]], index: int) -> str | None:
    """The program the terminal ran: the fence language of the code the previous message wrote."""
    fence = _FENCE.search(history[index - 1]["content"] or "") if index else None
    return _PROGRAM_OF_FENCE.get(fence.group(1).lower(), fence.group(1)) if fence else None
