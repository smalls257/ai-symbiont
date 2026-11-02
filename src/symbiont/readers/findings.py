"""Reader for lesson findings: tool-neutral JSON Lines written by any tool that found a mistake.

A developer who already runs some other review or analysis tool starts with its lessons: each
line of a findings file becomes one user-turn record tagged `correction`, so the existing
correction signal turns it into a pain point and nobody downstream knows which tool wrote it.
The format is documented in `docs/product/findings-format.md`.

Never spark safe: the findings come from the developer's own work and their privacy is unknown.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind, Provenance, Record

HARNESS = "findings"
FINDINGS_DIR = Path(".symbiont") / "findings"
PROVENANCE = Provenance(dataset="lesson-findings", license="own-work", spark_safe=False)
KINDS = frozenset({"mistake", "friction", "correction", "risk", "lesson"})
SEVERITIES = frozenset({"low", "medium", "high"})
_FIELDS = frozenset({"kind", "text", "files", "severity", "source", "date", "id"})
# Read by the correction signal as "the developer was told this went wrong".
_SIGNAL_TAG = "correction"


def findings_files(repo: Path) -> list[Path]:
    """The findings files a repository carries, in name order; none when it has no folder."""
    return sorted((Path(repo) / FINDINGS_DIR).glob("*.jsonl"))


def count_findings(repo: Path) -> int:
    """How many findings a repository carries, for the onboarding question.

    Raises ReadError naming file and line when a findings file is malformed: an unreadable
    file must not show up as "found 0".
    """
    return sum(1 for path in findings_files(repo) for _ in read(path, repo.name))


def read(path: Path, project: str) -> Iterator[Record]:
    """Yield one record per finding of a findings file, or of every file in a folder.

    Raises ReadError naming file and line for anything that is not a valid finding.
    """
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for file in files:
        yield from _read_file(file, project)


def _read_file(path: Path, project: str) -> Iterator[Record]:
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            yield _record(_finding(path, line_no, line), path, project, line_no)


def _finding(path: Path, line_no: int, line: str) -> dict[str, Any]:
    """The validated JSON object of one line."""
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise ReadError(path, line_no, f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReadError(path, line_no, "a finding must be a JSON object")
    problem = _problem(data)
    if problem is not None:
        raise ReadError(path, line_no, problem)
    return data


def _problem(data: dict[str, Any]) -> str | None:
    """What is wrong with a finding, naming the key; None when it is valid."""
    unknown = sorted(set(data) - _FIELDS)
    if unknown:
        return f"unknown key {unknown[0]!r}"
    checks = (
        _text_problem,
        lambda finding: _choice_problem(finding, "kind", KINDS, required=True),
        lambda finding: _choice_problem(finding, "severity", SEVERITIES, required=False),
        _files_problem,
        _names_problem,
        _date_problem,
    )
    return next((found for check in checks if (found := check(data)) is not None), None)


def _text_problem(data: dict[str, Any]) -> str | None:
    text = data.get("text")
    if isinstance(text, str) and text.strip():
        return None
    return "key 'text' must be a non-empty string"


def _choice_problem(
    data: dict[str, Any], key: str, allowed: frozenset[str], *, required: bool
) -> str | None:
    if (key not in data and not required) or data.get(key) in allowed:
        return None
    return f"key {key!r} must be one of {', '.join(sorted(allowed))}"


def _files_problem(data: dict[str, Any]) -> str | None:
    files = data.get("files", [])
    if isinstance(files, list) and all(isinstance(f, str) and f for f in files):
        return None
    return "key 'files' must be a list of path strings"


def _names_problem(data: dict[str, Any]) -> str | None:
    for key in ("source", "id"):
        if key in data and not (isinstance(data[key], str) and data[key]):
            return f"key {key!r} must be a non-empty string"
    return None


def _date_problem(data: dict[str, Any]) -> str | None:
    if "date" not in data:
        return None
    try:
        datetime.fromisoformat(data["date"])
    except (TypeError, ValueError):
        return "key 'date' must be an ISO-8601 date or time"
    return None


def _record(data: dict[str, Any], path: Path, project: str, line_no: int) -> Record:
    tags = [_SIGNAL_TAG, f"finding:{data['kind']}"]
    if "severity" in data:
        tags.append(f"severity:{data['severity']}")
    if "source" in data:
        tags.append(f"source:{data['source']}")
    return Record(
        harness=HARNESS,
        project=project,
        session_id=f"findings:{path.name}",
        step=line_no,
        kind=Kind.USER_TURN,
        raw=data["text"],
        provenance=PROVENANCE,
        ts=data.get("date"),
        files=tuple(data.get("files", ())),
        tags=tuple(tags),
    )
