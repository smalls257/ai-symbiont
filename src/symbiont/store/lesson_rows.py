"""Reading a lesson back from the JSON the lessons table stores."""

import json
from typing import Any

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
