"""Scrub credentials out of lesson text before any remote-bound use.

A lesson quotes real commands and output; a token pasted into a command must not reach a
remote-bound prompt or the weights of an adapter that answers a remote model. The patterns mirror
`.gitleaks.toml` plus common provider token shapes. Pure: text in, text out.
"""

from dataclasses import replace

from symbiont.miner.credential_patterns import REDACTED, scrub
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signature

__all__ = ["REDACTED", "scrub", "scrubbed"]


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
        fix_commands=tuple(scrub(command) for command in lesson.fix_commands),
        error_lines=tuple(scrub(line) for line in lesson.error_lines),
        asked=scrub(lesson.asked),
        agent_intent=scrub(lesson.agent_intent),
    )
