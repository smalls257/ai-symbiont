"""Scrub credentials out of lesson text before any Spark-bound use.

A lesson quotes real commands and output; a token pasted into a command must not reach a Spark-
bound prompt or the weights of an adapter that answers Spark. The patterns live in
`credential_scrub.py`. Pure: text in, text out.
"""

from dataclasses import replace

from symbiont.miner.credential_scrub import scrub
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signature


def scrubbed(lesson: Lesson) -> Lesson:
    """The lesson with every text field scrubbed, its signature key included."""
    pain = lesson.pain_point
    key = tuple(scrub(part) for part in pain.signature.key)
    unresolved = lesson.unresolved_because
    return replace(
        lesson,
        pain_point=PainPoint(
            Signature(pain.signature.signal, key), pain.session_id, pain.step, pain.record_refs
        ),
        quote=scrub(lesson.quote),
        resolution=tuple(scrub(step) for step in lesson.resolution),
        unresolved_because=None if unresolved is None else scrub(unresolved),
        changed_alongside=tuple(scrub(step) for step in lesson.changed_alongside),
        error_lines=tuple(scrub(line) for line in lesson.error_lines),
        expected_vs_actual=tuple(scrub(line) for line in lesson.expected_vs_actual),
    )
