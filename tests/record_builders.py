"""Hand-built records for miner tests: one session, steps numbered by position."""

import difflib
from dataclasses import replace

from symbiont.records.schema import Kind, Provenance, Record

PUBLIC = Provenance(dataset="synthetic", license="CC-BY-4.0", spark_safe=True)


def _record(kind: Kind, raw: str = "", **fields) -> Record:
    return Record(
        harness="openhands",
        project="tobymao/sqlglot",
        session_id="s1",
        step=-1,
        kind=kind,
        raw=raw,
        provenance=PUBLIC,
        **fields,
    )


def run(command: str, exit_code: int | None = 0, output: str = "") -> Record:
    return _record(Kind.COMMAND, output, command=command, exit_code=exit_code)


def view(path: str, line_range: tuple[int, int] | None = None, exit_code: int | None = 0) -> Record:
    return _record(
        Kind.READ, f"contents of {path}", files=(path,), exit_code=exit_code, line_range=line_range
    )


def edit(path: str, exit_code: int | None = 0, diff: str | None = "-a\n+b\n") -> Record:
    return _record(Kind.EDIT, "edited", files=(path,), diff=diff, exit_code=exit_code)


def replace_text(path: str, old: str, new: str, exit_code: int | None = 0) -> Record:
    """A str_replace edit, diffed the way the OpenHands reader diffs it."""
    lines = lambda text: [line + "\n" for line in text.splitlines()]  # noqa: E731
    diff = "".join(difflib.unified_diff(lines(old), lines(new), f"a/{path}", f"b/{path}"))
    return edit(path, exit_code=exit_code, diff=diff)


def user(text: str, tags: tuple[str, ...] = ()) -> Record:
    return _record(Kind.USER_TURN, text, tags=tags)


def review(path: str, hunk: str, comment: str) -> Record:
    """A reviewer's comment on a hunk of `path` (the hunk as GitHub shows it)."""
    return _record(Kind.REVIEW_COMMENT, comment, files=(path,), diff=hunk)


def say(text: str) -> Record:
    return _record(Kind.AGENT_TURN, text)


def session(*records: Record) -> list[Record]:
    """Number the steps in order, as a reader would."""
    return [replace(r, step=i) for i, r in enumerate(records)]
