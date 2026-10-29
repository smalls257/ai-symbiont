"""Route B's nightly rows from stored lessons: self-study Q&A and situation to corrected action.

Every answer quotes the stored lesson: Q&A rows answer with the three-part card
(`core.notes.render_lesson`), and a lesson with no fix gets no action row, since there is no
corrected action to teach. One verify question per lesson uses a wording no training row uses,
so verify measures the lesson, not the prompt. Pure: lessons in, rows out.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from symbiont.core.notes import check_to_run, happened, render_lesson, resolution_clause
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.trained import lesson_id

# Glimmer's template asks for high reasoning unless the turn names one (scripts/routeb/cards.py).
REASONING = "Reasoning strength: low."
NEXT = "What is your next action?"
NO_PATH = "-"

Messages = list[dict[str, str]]


@dataclass(frozen=True)
class TrainingRow:
    """One chat row, with the lesson and row kind it came from (ids only travel in manifests)."""

    lesson_id: str
    kind: str
    messages: Messages


@dataclass(frozen=True)
class VerifyQuestion:
    """A held-out wording of one lesson's question, asked of both Glimmer names after install."""

    question_id: str
    lesson_id: str
    text: str


def memory_system(repo: str) -> str:
    """The memory turn's system prompt; the verify step asks under the same one."""
    return (
        f"You are Glimmer, working in the {repo} repository. Answer in plain prose, "
        f"naming exact files, commands and checks.\n\n{REASONING}"
    )


def agent_system(repo: str) -> str:
    """The agent turn's system prompt for situation-to-action rows."""
    return (
        f"You are Glimmer, a coding agent in the {repo} repository with a bash shell. "
        f"Say your next action in one or two sentences.\n\n{REASONING}"
    )


def training_rows(repo: str, lessons: Sequence[Lesson]) -> list[TrainingRow]:
    """Every row of every lesson: self-study first, then the corrected action when one exists."""
    return [row for lesson in lessons for row in _rows_of(repo, lesson)]


def verify_questions(repo: str, lessons: Sequence[Lesson]) -> list[VerifyQuestion]:
    """One held-out question per lesson, worded unlike any training row."""
    asked = "Before I touch {subject} in {repo}, what should I know?"
    return [
        VerifyQuestion(
            f"{lesson_id(lesson)}-q",
            lesson_id(lesson),
            asked.format(subject=_subject(lesson.pain_point.signature), repo=repo),
        )
        for lesson in lessons
    ]


def _rows_of(repo: str, lesson: Lesson) -> list[TrainingRow]:
    """The self-study rows, then the corrected action when the history holds a fix."""
    rows = _self_study(repo, lesson)
    if lesson.resolution:
        rows.append(_corrected_action(repo, lesson))
    return rows


def _self_study(repo: str, lesson: Lesson) -> list[TrainingRow]:
    """Two questions about the trouble, both answered by the whole lesson card."""
    subject = _subject(lesson.pain_point.signature)
    asked = [
        f"In {repo}, what went wrong last time with {subject}?",
        f"In {repo}, what do you remember about {subject}?",
    ]
    card = render_lesson(lesson)
    return [
        TrainingRow(lesson_id(lesson), "self-study", _chat(memory_system(repo), question, card))
        for question in asked
    ]


def _corrected_action(repo: str, lesson: Lesson) -> TrainingRow:
    """The agent is about to repeat the step; the answer is the recorded fix and the check."""
    signature = lesson.pain_point.signature
    situation = f"Task in {repo}: {_SITUATIONS[signature.signal](signature)} {NEXT}"
    answer = (
        f"Last time {happened(signature)}; it was resolved when {resolution_clause(lesson)}. "
        f"{check_to_run(signature)}."
    )
    return TrainingRow(lesson_id(lesson), "action", _chat(agent_system(repo), situation, answer))


def _chat(system: str, question: str, answer: str) -> Messages:
    """One system, user, assistant row."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]


def _command(signature: Signature) -> str:
    """The command text of a failed-command signature, without placeholder parts."""
    *target, _ = signature.key
    return " ".join(part for part in target if part != NO_PATH)


def _subject(signature: Signature) -> str:
    """What a lesson is about, in backticks, for a question."""
    if signature.signal is Signal.FAILED_COMMAND:
        return f"`{_command(signature)}`"
    if signature.signal is Signal.LOOP:
        return f"`{signature.key[1]}`"
    if signature.signal is Signal.CORRECTION and signature.key[0] == NO_PATH:
        return "that request"
    return f"`{signature.key[0]}`"


def _request(signature: Signature) -> str:
    """`request`, or `request about <path>` when the correction names a file."""
    path = signature.key[0]
    return "request" if path == NO_PATH else f"request about `{path}`"


_SITUATIONS: dict[Signal, Callable[[Signature], str]] = {
    Signal.FAILED_COMMAND: lambda sig: f"you are about to run `{_command(sig)}`.",
    Signal.REWORKED_EDIT: lambda sig: f"you are about to edit `{sig.key[0]}`.",
    Signal.REVIEW_FLAG: lambda sig: f"you are about to submit your change to `{sig.key[0]}`.",
    Signal.CORRECTION: lambda sig: f"you are about to act on the developer's {_request(sig)}.",
    Signal.LOOP: lambda sig: f"you are about to go back to `{sig.key[1]}` again.",
    Signal.BLAST_RADIUS: lambda sig: f"you are about to edit `{sig.key[0]}`.",
}
