"""Reading a lesson back from the JSON the lessons table stores."""

import json
from dataclasses import asdict
from typing import Any

from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature


def lesson_from_json(body: str) -> Lesson:
    """Rebuild a lesson from its stored JSON."""
    data = json.loads(body)
    return Lesson(
        pain_point=pain_point_from_dict(data["pain_point"]),
        quote=data["quote"],
        resolution=tuple(data["resolution"]),
        unresolved_because=data["unresolved_because"],
        spark_safe=data["spark_safe"],
        sources=tuple((ref[0], ref[1]) for ref in data["sources"]),
        task_ids=tuple(data["task_ids"]),
        # Rows written before this field existed recorded no such changes.
        changed_alongside=tuple(data.get("changed_alongside", ())),
        # Rows written before this field existed name no dataset: a private one stays blocked.
        private_datasets=tuple(data.get("private_datasets", ())),
        # Rows written before these fields existed carry no error lines or files.
        error_lines=tuple(data.get("error_lines", ())),
        files=tuple(data.get("files", ())),
        # Rows written before this field existed name no fix; a re-mining fills it in.
        fix=FixKind(data["fix"]) if data.get("fix") else None,
    )


def pain_point_from_dict(data: dict[str, Any]) -> PainPoint:
    """A pain point from its stored dict."""
    signature = data["signature"]
    return PainPoint(
        signature=Signature(Signal(signature["signal"]), tuple(signature["key"])),
        session_id=data["session_id"],
        step=data["step"],
        record_refs=tuple((ref[0], ref[1]) for ref in data["record_refs"]),
    )


def lesson_row(project: str, lesson: Lesson) -> tuple[str, str, int, bool, str]:
    """The lessons-table row for a lesson."""
    pain = lesson.pain_point
    return (project, pain.session_id, pain.step, lesson.spark_safe, lesson_json(lesson))


def lesson_json(lesson: Lesson) -> str:
    """Serialize a lesson for the lessons table."""
    return json.dumps(asdict(lesson))
