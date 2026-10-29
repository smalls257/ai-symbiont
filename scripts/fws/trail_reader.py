"""Reader for TRAIL (patronus-ai/trail-benchmark): smolagents span trees with annotated errors.

Every "Step N" span (manager and managed agents alike) is one record, on one timeline by start
time, numbered from 1 after the task (record 0). An error's `location` is a span id, placed on
the innermost step holding it. TRAIL is gated on Hugging Face ("do not reshare outside a gated or
private repository"): text stays in memory, nothing read here reaches a tracked file.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from annotated import AnnotatedTrace, TaskKind

from symbiont.readers.errors import ReadError
from symbiont.records.schema import Kind, Provenance, Record

SOURCE = "trail"
HARNESS = "smolagents"
FRAMEWORK = "smolagents CodeAgent (OpenInference spans)"
PROVENANCE = Provenance(
    dataset="patronus-ai/trail-benchmark",
    license="MIT; gated on Hugging Face, local use only",
    spark_safe=False,
)
# Trace directory, annotation directory, task kind; as laid out in the dataset repository.
SPLITS = {
    "swe_bench": ("data/SWE Bench", "processed_annotations_swe_bench", TaskKind.CODING),
    "gaia": ("data/GAIA", "processed_annotations_gaia", TaskKind.WEB_QA),
}
_STEP_NAME = re.compile(r"Step \d+")
_FINAL_ANSWER = "FinalAnswerTool"
_CODE_AGENT = "CodeAgent.run"


@dataclass(frozen=True)
class _StepSpan:
    """A step span, the agent that ran it and every span id beneath it."""

    span: dict[str, Any]
    agent: str
    inside: frozenset[str]


@dataclass(frozen=True)
class TrailRead:
    """Every readable trace, and the files that could not be read with the reason."""

    traces: list[AnnotatedTrace]
    unreadable: list[ReadError]
    # Annotations with no trace_id of their own, paired with their trace by file name (the
    # dataset's layout: both files carry the trace id as their name).
    paired_by_file_name: int
    # Annotation files whose trace file is absent: counted, since no trace means no steps.
    annotations_without_trace: int


def read_trail(root: Path) -> TrailRead:
    """Read both TRAIL splits under `root`; a file that does not parse is kept as its ReadError."""
    traces: list[AnnotatedTrace] = []
    unreadable: list[ReadError] = []
    by_name = 0
    for split, (trace_dir, annotation_dir, _) in SPLITS.items():
        for path in sorted((root / trace_dir).glob("*.json")):
            try:
                annotation = _load(root / annotation_dir / path.name)
                by_name += "trace_id" not in annotation
                traces.append(_read_pair(path, annotation, split))
            except ReadError as exc:
                unreadable.append(exc)
    return TrailRead(traces, unreadable, by_name, _orphan_annotations(root))


def _orphan_annotations(root: Path) -> int:
    """Annotation files with no trace file of the same name in their split."""
    return sum(
        not (root / trace_dir / path.name).is_file()
        for trace_dir, annotation_dir, _ in SPLITS.values()
        for path in (root / annotation_dir).glob("*.json")
    )


def _read_pair(trace_path: Path, annotation: dict[str, Any], split: str) -> AnnotatedTrace:
    """One trace file and its annotation; raises ReadError naming the trace file."""
    annotation = {"trace_id": trace_path.stem} | annotation
    try:
        return trace_from(_load(trace_path), annotation, split)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ReadError):
            raise
        raise ReadError(trace_path, 0, f"not a TRAIL trace: {exc!r}") from exc


def _load(path: Path) -> dict[str, Any]:
    """The decoded json object; raises ReadError naming the file and line."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReadError(path, 0, "file is missing") from exc
    except json.JSONDecodeError as exc:
        raise ReadError(path, exc.lineno, f"not json: {exc.msg}") from exc
    if not isinstance(document, dict):
        raise ReadError(path, 1, "top level is not an object")
    return document


def trace_from(trace: dict[str, Any], annotation: dict[str, Any], split: str) -> AnnotatedTrace:
    """One trace and its annotation as an AnnotatedTrace; raises KeyError on a missing field."""
    trace_id = trace["trace_id"]
    if annotation["trace_id"] != trace_id:
        raise ValueError(f"annotation for {annotation['trace_id']} paired with trace {trace_id}")
    steps = sorted(_step_spans(trace["spans"]), key=lambda step: step.span["timestamp"])
    session = f"{SOURCE}:{split}:{trace_id}"
    records = [_task_record(session, split)]
    records += [_step_record(step, session, split, n) for n, step in enumerate(steps, start=1)]
    placed = [_step_of(error["location"], steps) for error in annotation["errors"]]
    return AnnotatedTrace(
        source=SOURCE,
        split=split,
        framework=FRAMEWORK,
        task_kind=SPLITS[split][2],
        records=tuple(records),
        error_steps=tuple(sorted({n for n in placed if n is not None})),
        unplaced_errors=sum(n is None for n in placed),
    )


def _step_spans(spans: list[dict[str, Any]], agent: str = "") -> Iterator[_StepSpan]:
    """Every "Step N" span below `spans`, with the nearest agent run above it."""
    for span in spans:
        name = span["span_name"]
        if _STEP_NAME.fullmatch(name):
            yield _StepSpan(span, agent, frozenset(_span_ids(span)))
        yield from _step_spans(
            span.get("child_spans", []), name if name.endswith(".run") else agent
        )


def _span_ids(span: dict[str, Any]) -> Iterator[str]:
    """The span's id and the ids of every span beneath it."""
    yield span["span_id"]
    for child in span.get("child_spans", []):
        yield from _span_ids(child)


def _step_of(location: str, steps: list[_StepSpan]) -> int | None:
    """The innermost step (numbered from 1) holding the span, or None outside every step."""
    holding = [n for n, step in enumerate(steps, start=1) if location in step.inside]
    return min(holding, key=lambda number: len(steps[number - 1].inside)) if holding else None


def _task_record(session: str, split: str) -> Record:
    """Record 0: the task was handed to the agent (its text is not needed by any label)."""
    return Record(
        harness=HARNESS,
        project=f"{SOURCE}:{split}",
        session_id=session,
        step=0,
        kind=Kind.USER_TURN,
        raw="",
        provenance=PROVENANCE,
    )


def _step_record(step: _StepSpan, session: str, split: str, number: int) -> Record:
    """One agent step as a COMMAND (tools or code ran) or the final AGENT_TURN."""
    tools = _tool_names(step.span)
    final = _FINAL_ANSWER in tools
    words = (["python"] if step.agent == _CODE_AGENT else []) + [t for t in tools if not final]
    return Record(
        harness=HARNESS,
        project=f"{SOURCE}:{split}",
        session_id=session,
        step=number,
        kind=Kind.AGENT_TURN if final else Kind.COMMAND,
        raw=str(step.span.get("span_attributes", {}).get("output.value", "")),
        provenance=PROVENANCE,
        ts=step.span["timestamp"],
        command=None if final else " ".join(words) or None,
        exit_code=None if final else int(step.span.get("status_code") == "Error"),
    )


def _tool_names(step_span: dict[str, Any]) -> list[str]:
    """Names of the tool spans directly under a step, in order."""
    return [
        child["span_name"]
        for child in step_span.get("child_spans", [])
        if child.get("span_attributes", {}).get("openinference.span.kind") == "TOOL"
    ]
