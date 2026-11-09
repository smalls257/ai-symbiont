"""A stored lesson reads back whole, including whether its target was the session's own script."""

import json
from dataclasses import replace

from symbiont.miner.fixes import FixKind
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signal, Signature
from symbiont.store.lesson_rows import lesson_from_json, lesson_json


def a_lesson() -> Lesson:
    signature = Signature(Signal.FAILED_COMMAND, ("python", "repro.py", "TypeError"))
    return Lesson(
        pain_point=PainPoint(signature, "s1", 1, (("s1", 1),)),
        quote="q",
        resolution=("ran `x`",),
        unresolved_because=None,
        remote_safe=True,
        sources=(("s1", 1),),
        fix=FixKind.CODE_FIX,
    )


def test_target_created_survives_a_round_trip():
    """Failure guarded against: every stored lesson reading back as a lasting script."""
    lesson = replace(a_lesson(), target_created=True)
    assert lesson_from_json(lesson_json(lesson)).target_created is True


def test_a_row_written_before_the_field_reads_as_not_created():
    body = json.loads(lesson_json(a_lesson()))
    del body["target_created"]
    assert lesson_from_json(json.dumps(body)).target_created is False
