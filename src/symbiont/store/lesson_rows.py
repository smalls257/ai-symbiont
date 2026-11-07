"""Reading a lesson back from the JSON the lessons table stores."""

import json
import re
from dataclasses import asdict
from typing import Any

from symbiont.miner.fix_words import phrase_from_old_steps
from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature

_OLD_RAN_STEP = re.compile(r"ran `([^`]+)`")


def _fix_commands_of(data: dict[str, Any]) -> tuple[str, ...]:
    """The commands the fix ran; rows from before the field read them off the old step wording."""
    if "fix_commands" in data:
        return tuple(data["fix_commands"])
    found = (_OLD_RAN_STEP.search(step) for step in data["resolution"])
    return tuple(match.group(1) for match in found if match)


def _plain_steps(steps: list[str], pain: PainPoint) -> tuple[str, ...]:
    """Steps as stored; rows from before the plain phrase (backticked paths and code) are re-worded.

    Done at read time so an old store reads plain without a re-mining.
    """
    if not any("`" in step for step in steps):
        return tuple(steps)
    failed = pain.signature.signal is Signal.FAILED_COMMAND
    phrase = phrase_from_old_steps(steps, pain.signature.key[0] if failed else "")
    return (phrase,) if phrase else ()


def _remote_safe_of(data: dict[str, Any]) -> bool:
    """The privacy flag, under its new name or the one rows carried before the rename.

    Raises ValueError naming the lesson for a missing or non-boolean flag:
    an unknown flag must never read as shareable.
    """
    pain = data["pain_point"]
    named = f"lesson of session {pain['session_id']!r} step {pain['step']}"
    for key in ("remote_safe", "spark_safe"):
        if key in data:
            flag = data[key]
            if not isinstance(flag, bool):
                raise ValueError(f"{named} stores {key}={flag!r}, not true or false")
            return flag
    raise ValueError(f"{named} stores no remote_safe flag")


def lesson_from_json(body: str) -> Lesson:
    """Rebuild a lesson from its stored JSON."""
    data = json.loads(body)
    pain = pain_point_from_dict(data["pain_point"])
    return Lesson(
        pain_point=pain,
        quote=data["quote"],
        resolution=_plain_steps(data["resolution"], pain),
        unresolved_because=data["unresolved_because"],
        remote_safe=_remote_safe_of(data),
        sources=tuple((ref[0], ref[1]) for ref in data["sources"]),
        task_ids=tuple(data["task_ids"]),
        # Rows written before this field existed recorded no such changes.
        changed_alongside=_plain_steps(data.get("changed_alongside", []), pain),
        # Rows written before this field existed name no dataset: a private one stays blocked.
        private_datasets=tuple(data.get("private_datasets", ())),
        # Rows written before these fields existed carry no error lines or files.
        error_lines=tuple(data.get("error_lines", ())),
        files=tuple(data.get("files", ())),
        # Rows written before this field existed name no fix; a re-mining fills it in.
        fix=FixKind(data["fix"]) if data.get("fix") else None,
        # Rows written before this field existed read as False: the script was never known created.
        target_created=data.get("target_created", False),
        # Rows written before these fields existed carry no turns around the failure.
        asked=data.get("asked", ""),
        agent_intent=data.get("agent_intent", ""),
        fix_commands=_fix_commands_of(data),
        # Rows written before this field existed counted one step per old-style resolution item.
        fix_steps=data.get("fix_steps", len(data["resolution"])),
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
    return (project, pain.session_id, pain.step, lesson.remote_safe, lesson_json(lesson))


def lesson_json(lesson: Lesson) -> str:
    """Serialize a lesson for the lessons table."""
    return json.dumps(asdict(lesson))
