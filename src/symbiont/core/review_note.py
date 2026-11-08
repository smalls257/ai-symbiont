"""Notes for review feedback: who flagged which file, their point, and how it ended.

A reviewer is a product name or "a teammate"; a key from before reviewers were named
(`(path,)`) reads "A reviewer". Split from `notes` to keep that module small.
"""

from symbiont.core.note_words import MIN_WHILE_CHARS, NOTE_CHARS, times
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signature
from symbiont.miner.story import story_of


def review_note(lesson: Lesson) -> str:
    """`CodeRabbit flagged `a.ts`: <point>. Last time: fixed by editing a.ts.`; no check line.

    The fix is the useful half, so a long point is cut to make the whole note fit.
    """
    signature = lesson.pain_point.signature
    ended = story_of(lesson).ended
    ending = f"Last time: {ended}." if ended else "No fix was found in the history."
    room = NOTE_CHARS - len(ending) - len(flagged(signature, "")) - len(": . ")
    return f"{flagged(signature, _cut_point(_point(signature), room))}. {ending}"


def review_warning(signature: Signature, count: int) -> str:
    """`CodeRabbit flagged `a.ts` 2 times before: <point>.`: the point is what to apply."""
    said = f"{flagged(signature, '')} {times(count)} before"
    point = _point(signature)
    return f"{said}: {point}." if point else f"{said}."


def flagged(signature: Signature, point: str | None = None) -> str:
    """`CodeRabbit flagged `a.ts`: <point>`, the point left out when there is none."""
    said = f"{_reviewer(signature)} flagged `{signature.key[0]}`"
    point = _point(signature) if point is None else point
    return f"{said}: {point}" if point else said


def _cut_point(point: str, room: int) -> str:
    """The point, cut at a word with an ellipsis to fit `room`; "" when almost nothing would fit."""
    if len(point) <= room:
        return point
    if room < MIN_WHILE_CHARS:
        return ""
    return point[: room - 1].rsplit(" ", 1)[0].rstrip(" ,(") + "…"


def _reviewer(signature: Signature) -> str:
    """The reviewer's product name or "A teammate"; "A reviewer" for a key from before names."""
    name = signature.key[1] if len(signature.key) > 1 else "A reviewer"
    return name[0].upper() + name[1:]


def _point(signature: Signature) -> str:
    return signature.key[2].rstrip(".") if len(signature.key) > 2 else ""
