"""What the memory model is asked and what it must answer: one line in three labeled parts.

The prompt is the situation in domain prose, built from the kind of trouble, never a score. A
reply that is not exactly one line of "Happened: ... -> Resolved: ... -> Check: ..." raises;
nothing repairs it. The same functions build the training rows and the live prompts.
"""

from dataclasses import dataclass

from symbiont.core.notes import check_to_run, happened, resolution_clause
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature

SYSTEM = (
    "You are a memory model of this developer's past work. Answer in one line: "
    "Happened: ... -> Resolved: ... -> Check: ..."
)
INSTRUCTION = "Write one line: what happened -> how it was resolved -> the check to run."
SEPARATOR = " -> "
LABELS = ("Happened: ", "Resolved: ", "Check: ")
# Three clauses with a command each fit easily; longer is the model rambling past the format.
MAX_NOTE_CHARS = 480


class InvalidNoteError(ValueError):
    """The memory model's reply is not one three-part line; the message says why, never the text."""


@dataclass(frozen=True)
class TrainingPair:
    """One supervised example: the prompt the service would send and the line to answer."""

    prompt: str
    line: str


def note_request(project: str, trouble: Signature) -> str:
    """The prompt for a note at a boundary step: where, what just happened, and the instruction."""
    return f"In {project}, {happened(trouble)}. {INSTRUCTION}"


def recall_request(project: str, question: str) -> str:
    """The prompt for one developer question about the project's history."""
    return f"In {project}, a question about earlier work: {question.strip()} {INSTRUCTION}"


def lesson_line(lesson: Lesson) -> str:
    """The line the memory model is taught for this lesson."""
    signature = lesson.pain_point.signature
    parts = (happened(signature), resolution_clause(lesson), check_to_run(signature))
    return SEPARATOR.join(label + part for label, part in zip(LABELS, parts, strict=True))


def training_pairs(project: str, lesson: Lesson) -> list[TrainingPair]:
    """The note prompt plus question prompts about the same trouble, all answered by one line."""
    line = lesson_line(lesson)
    signature = lesson.pain_point.signature
    prompts = [note_request(project, signature)]
    prompts += [recall_request(project, question) for question in _questions(signature)]
    return [TrainingPair(prompt, line) for prompt in prompts]


def _questions(signature: Signature) -> list[str]:
    """The questions a user might ask about a signature's trouble."""
    subject = _subject(signature)
    return [
        f"What went wrong last time with {subject}?",
        f"What do you remember about {subject}?",
        f"Is there anything I should know before working on {subject} again?",
    ]


def _subject(signature: Signature) -> str:
    """What a signature is about, in backticks, for a question."""
    if signature.signal is Signal.FAILED_COMMAND:
        *target, _ = signature.key
        return f"`{' '.join(part for part in target if part != '-')}`"
    return f"`{signature.key[0]}`" if signature.signal is not Signal.CORRECTION else "that request"


def note_line(reply: str) -> str:
    """The reply as a note, or InvalidNoteError when it is not one line in the three-part form."""
    line = reply.strip()
    if not line:
        raise InvalidNoteError("the memory model sent an empty reply")
    if "\n" in line:
        raise InvalidNoteError("the memory model sent more than one line")
    if len(line) > MAX_NOTE_CHARS:
        raise InvalidNoteError(f"the memory model's line is over {MAX_NOTE_CHARS} characters")
    parts = line.split(SEPARATOR)
    if len(parts) != len(LABELS):
        raise InvalidNoteError(f"the memory model's line has {len(parts)} parts, not 3")
    for label, part in zip(LABELS, parts, strict=True):
        if not part.startswith(label) or not part.removeprefix(label).strip():
            raise InvalidNoteError(f"the memory model's line lacks a filled {label.strip()} part")
    return line
