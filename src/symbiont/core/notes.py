"""Notes: a Decision or a lesson rendered as plain sentences for the agent to read.

A lesson reads as three parts: what happened, how it was resolved, the check to
run. Domain prose only: no scores, feature names or thresholds.
"""

from collections.abc import Callable, Collection, Sequence
from enum import StrEnum

from symbiont.core.slot import Decision
from symbiont.miner.failure_keys import broke_in_words
from symbiont.miner.fix_words import resolution_phrase
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.story import story_of
from symbiont.records.schema import Record

DEFAULT_MAX_NOTES = 2
NO_PATH = "-"
TITLE_QUOTE_CHARS = 60
# A note is read in passing by the agent; owner: "word vomit" is the failure to avoid.
NOTE_CHARS = 300
MIN_WHILE_CHARS = 30


class NoteKind(StrEnum):
    """What a note is for; one more member (with its own templates) adds a kind."""

    WARN = "warn"
    RECALL = "recall"


def render(
    decision: Decision,
    *,
    max_notes: int = DEFAULT_MAX_NOTES,
    kinds: Collection[NoteKind] = tuple(NoteKind),
    lessons: Sequence[Lesson] = (),
) -> list[str]:
    """Up to `max_notes` sentences across the chosen kinds, in NoteKind order.

    A warning backed by one of `lessons` also says how it was resolved and what to check.
    """
    notes = [
        note for kind in NoteKind if kind in kinds for note in _BY_KIND[kind](decision, lessons)
    ]
    return [note for note in notes if note][:max_notes]


def render_lesson(lesson: Lesson) -> str:
    """A failed command as its story; any other trouble as what happened, resolution and check."""
    signature = lesson.pain_point.signature
    if signature.signal is Signal.FAILED_COMMAND:
        return story_note(lesson)
    if signature.signal is Signal.REVIEW_FLAG:
        return review_note(lesson)
    happened = _HAPPENED[signature.signal](signature)
    return _joined(f"What happened: {happened}.", _resolved(lesson), _check(signature))


def review_note(lesson: Lesson) -> str:
    """`CodeRabbit flagged `a.ts`: <point>. Last time: fixed by editing a.ts.`; no check line."""
    ended = story_of(lesson).ended
    return _clipped(_joined(f"{_flagged(lesson.pain_point.signature)}.", _ended_sentence(ended)))


def _ended_sentence(ended: str) -> str:
    return f"Last time: {ended}." if ended else "No fix was found in the history."


def _reviewer(signature: Signature) -> str:
    """The reviewer's product name, or "A reviewer" for a key from before reviewers were named."""
    return signature.key[1] if len(signature.key) > 1 else "A reviewer"


def _flagged(signature: Signature) -> str:
    """`CodeRabbit flagged `a.ts`: <point>`, the point left out when the key has none."""
    point = signature.key[2] if len(signature.key) > 2 else ""
    said = f"{_reviewer(signature)} flagged `{signature.key[0]}`"
    return f"{said}: {point.rstrip('.')}" if point else said


def story_note(lesson: Lesson) -> str:
    """The story as `While <working on>: <what broke>. Last time: <how it ended>.`, short.

    No labels, scores or checks: the agent reads a colleague's account. The While clause gives way
    first when the note would run long, and is left out when the work is unknown.
    """
    story = story_of(lesson)
    ending = (
        f"Last time: {story.ended}." if lesson.resolution else "No fix was found in the history."
    )
    body = _clipped(f"{story.broke}. {ending}" if story.broke else ending)
    room = NOTE_CHARS - len(body) - len("While : ")
    if not story.working_on or room < MIN_WHILE_CHARS:
        return body
    working = (
        story.working_on if len(story.working_on) <= room else story.working_on[: room - 1] + "…"
    )
    return f"While {working}: {body}"


def _clipped(text: str) -> str:
    """The text cut to NOTE_CHARS at a word boundary, marked with an ellipsis."""
    if len(text) <= NOTE_CHARS:
        return text
    return text[: NOTE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,(") + "…"


def happened(signature: Signature) -> str:
    """What the trouble was, as a clause: "`pytest x` failed with ImportError"."""
    return _HAPPENED[signature.signal](signature)


def title_of(signature: Signature, group_name: str = "") -> str:
    """The heading a page gives the trouble; a correction is named, not quoted as "corrected on".

    `group_name` is the session model's name for the correction group, when one exists.
    """
    if signature.signal is not Signal.CORRECTION:
        return happened(signature)
    if group_name:
        return group_name
    quoted = signature.key[1]
    short = quoted if len(quoted) <= TITLE_QUOTE_CHARS else quoted[: TITLE_QUOTE_CHARS - 1] + "…"
    return f'You corrected the agent: "{short}"'


def _joined(*sentences: str) -> str:
    """The non-empty sentences, one space apart."""
    return " ".join(sentence for sentence in sentences if sentence)


def specific_check(signature: Signature) -> str:
    """The check history supports as a clause without the "Check:" label; "" when none."""
    return _check(signature).removeprefix("Check: ").rstrip(".")


def check_to_run(signature: Signature) -> str:
    """The check for this kind of trouble, as a clause without the "Check:" label."""
    return specific_check(signature) or _FIXED_FORMAT_CHECKS[signature.signal].rstrip(".")


def resolution_clause(lesson: Lesson) -> str:
    """How the lesson was resolved, or that the history shows no fix, as a clause."""
    if not lesson.resolution:
        return "no fix was found in the history"
    return f"you {resolution_phrase(lesson.resolution)}"


def _recalls(decision: Decision, lessons: Sequence[Lesson]) -> list[str]:
    """One sentence per recalled record."""
    return [_recalled(record) for record in decision.recall]


def _warning(decision: Decision, lessons: Sequence[Lesson]) -> list[str]:
    """The warning sentence for the decision's trouble, with the fix when a lesson backs it."""
    if decision.trouble is None:
        return []
    said = _TEMPLATES[decision.trouble.signal](decision.trouble, len(decision.why))
    backing = _backing_lesson(decision, lessons)
    if backing is None:
        return [said]
    return [_joined(said, _resolved(backing), _check(decision.trouble))]


def _backing_lesson(decision: Decision, lessons: Sequence[Lesson]) -> Lesson | None:
    """The latest lesson behind the warning, preferring one whose fix is known."""
    cited = set(decision.why)
    backing = [lesson for lesson in lessons if lesson.pain_point in cited]
    resolved = [lesson for lesson in backing if lesson.resolution]
    preferred = resolved or backing
    return preferred[-1] if preferred else None


def _resolved(lesson: Lesson) -> str:
    """How a lesson was resolved, and what else changed between the failure and the pass."""
    meanwhile = ""
    if lesson.changed_alongside:
        changed = resolution_phrase(lesson.changed_alongside)
        meanwhile = f" Before it passed you also {changed}."
    if not lesson.resolution:
        return "No fix was found in the history." + meanwhile
    return f"Last time: {resolution_phrase(lesson.resolution)}.{meanwhile}"


def _times(count: int) -> str:
    """`once` or `N times`, for prose."""
    return "once" if count == 1 else f"{count} times"


def _failed_command(signature: Signature, count: int) -> str:
    """Note for a command that failed the same way before."""
    *target, error = signature.key
    command = " ".join(part for part in target if part != NO_PATH)
    broke = "a non-zero exit" if error.startswith("exit ") else broke_in_words(error)
    return f"This command has failed {_times(count)} before: `{command}` -> {broke}."


def _reworked_edit(signature: Signature, count: int) -> str:
    """Note for a file whose edits were redone before."""
    return f"You have redone your edits to `{signature.key[0]}` {_times(count)} before."


def _review_flag(signature: Signature, count: int) -> str:
    """Note for a file a reviewer flagged before."""
    return f"{_reviewer(signature)} flagged `{signature.key[0]}` {_times(count)} before."


def _correction(signature: Signature, count: int) -> str:
    """Note for an earlier user correction."""
    path, words = signature.key
    where = "" if path == NO_PATH else f" about `{path}`"
    return f"You were corrected{where} {_times(count)} before, on: {words}."


def _loop(signature: Signature, count: int) -> str:
    """Note for an earlier session that went in circles."""
    kind, target = signature.key[0], signature.key[1]
    what = f"the command `{target}`" if kind == "command" else f"`{target}`"
    return f"You went in circles over {what} in an earlier session ({_times(count)})."


def _blast_radius(signature: Signature, count: int) -> str:
    """Note for an edit that broke its dependents' tests before."""
    edited, dependent = signature.key
    return (
        f"You edited `{edited}` before without touching `{dependent}`, "
        "and the tests that cover it broke."
    )


def _recalled(record: Record) -> str:
    """A sentence for one recalled record; empty when it has neither command nor file."""
    if record.command:
        return f"Earlier in this project you ran `{record.command}`."
    if record.files:
        return f"Earlier in this project you worked on `{record.files[0]}`."
    return ""


def _command_of(signature: Signature) -> str:
    """The command text of a command signature."""
    *target, _ = signature.key
    return " ".join(part for part in target if part != NO_PATH)


def _where(path: str) -> str:
    """` about <path>` for a path, empty for none."""
    return "" if path == NO_PATH else f" about `{path}`"


_HAPPENED: dict[Signal, Callable[[Signature], str]] = {
    Signal.FAILED_COMMAND: lambda sig: (
        f"`{_command_of(sig)}` failed with {broke_in_words(sig.key[-1])}"
    ),
    Signal.REWORKED_EDIT: lambda sig: f"your edits to `{sig.key[0]}` were redone",
    Signal.REVIEW_FLAG: _flagged,
    Signal.CORRECTION: lambda sig: f"you were corrected{_where(sig.key[0])} on: {sig.key[1]}",
    Signal.LOOP: lambda sig: f"you went in circles over `{sig.key[1]}`",
    Signal.BLAST_RADIUS: lambda sig: (
        f"editing `{sig.key[0]}` without reading `{sig.key[1]}` broke the tests that cover it"
    ),
}

_CHECKS: dict[Signal, Callable[[Signature], str]] = {
    Signal.FAILED_COMMAND: lambda sig: (
        f"Check: run `{_command_of(sig)}` and confirm it passes before moving on."
    ),
    Signal.REWORKED_EDIT: lambda sig: f"Check: read the current `{sig.key[0]}` before editing it.",
    Signal.BLAST_RADIUS: lambda sig: (
        f"Check: read `{sig.key[1]}` and run its tests before changing `{sig.key[0]}`."
    ),
}


# Only for the fixed three-part memory line and training rows, which need a clause in every slot.
# A note to the agent leaves the check out instead of saying something generic.
_FIXED_FORMAT_CHECKS = {
    Signal.REVIEW_FLAG: "confirm your change answers the reviewer's comment.",
    Signal.CORRECTION: "confirm your next step does what the developer asked.",
    Signal.LOOP: "if you are about to repeat it, stop and try another approach.",
}


def _check(signature: Signature) -> str:
    """The check to run for a signature, or "" when the history says nothing specific."""
    make = _CHECKS.get(signature.signal)
    return make(signature) if make else ""


_TEMPLATES: dict[Signal, Callable[[Signature, int], str]] = {
    Signal.FAILED_COMMAND: _failed_command,
    Signal.REWORKED_EDIT: _reworked_edit,
    Signal.REVIEW_FLAG: _review_flag,
    Signal.CORRECTION: _correction,
    Signal.LOOP: _loop,
    Signal.BLAST_RADIUS: _blast_radius,
}

_BY_KIND: dict[NoteKind, Callable[[Decision, Sequence[Lesson]], list[str]]] = {
    NoteKind.WARN: _warning,
    NoteKind.RECALL: _recalls,
}
