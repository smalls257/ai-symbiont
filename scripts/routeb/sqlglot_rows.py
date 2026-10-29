"""Training rows for the sqlglot adapter: self-study Q&A and situation to corrected action.

Recall alone is proven (LCAP); behavior is the open question, so half the rows put Glimmer in the
state a run of its own stalled in (file open, read many times, no edit) and train the corrected
action, a hard directive naming the place and the test. Q&A rows answer under a memory turn, action
rows under an agent turn, both in Glimmer's template with reasoning set to low (cards.py). Held-out
questions use a wording no training row uses. Pure: lessons in, rows out.
"""

from dataclasses import dataclass

from sqlglot_lessons import Lesson, LessonSource, Stall

REASONING = "Reasoning strength: low."  # the template asks for high unless the turn names one
MEMORY_SYSTEM = (
    "You are Glimmer, working in the tobymao/sqlglot repository. Answer in plain prose, "
    f"naming exact files, places and commands.\n\n{REASONING}"
)
AGENT_SYSTEM = (
    "You are Glimmer, a coding agent fixing an issue in the tobymao/sqlglot repository with a "
    f"bash shell. Say your next action in one or two sentences.\n\n{REASONING}"
)
NEXT = "What is your next action?"

Messages = list[dict[str, str]]


@dataclass(frozen=True)
class TrainingRow:
    """One chat row with the lesson and row kind it came from (the row index keeps those two)."""

    lesson_id: str
    kind: str
    messages: Messages


def _chat(system: str, question: str, answer: str) -> Messages:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]


def subject(lesson: Lesson) -> str:
    """How rows name the lesson's situation: the quoted issue, or the situation sentence."""
    if lesson.source in (LessonSource.OWN_SOLVE, LessonSource.OWN_FAILURE):
        return f'the issue "{lesson.title}"'
    situation = lesson.title.rstrip(".")
    return situation[:1].lower() + situation[1:]


def directive(lesson: Lesson) -> str:
    """The corrected action: open, go to the place, edit now, run the check."""
    return (
        f"Open `{lesson.file}`, go to {lesson.place}, make the edit now, then run "
        f"`{lesson.check}`. Do not write scratch scripts or re-read files you have already read."
    )


def self_study(lesson: Lesson) -> list[TrainingRow]:
    """Q&A rows: the whole card, then (for a code fix) where it went and the test that checks it."""
    about = subject(lesson)
    asked = [("card", f"In sqlglot, {about}: what do you remember?", lesson.card())]
    if lesson.source != LessonSource.REPO_HABIT:
        asked += [
            ("resolved", f"In sqlglot, {about}: where did the fix go?", lesson.resolved),
            ("check", f"In sqlglot, {about}: which check proves it?", f"Run `{lesson.check}`."),
        ]
    return [
        TrainingRow(lesson.lesson_id, kind, _chat(MEMORY_SYSTEM, question, answer))
        for kind, question, answer in asked
    ]


def _opened(lesson: Lesson) -> str:
    stall = lesson.stall
    when = f" at step {stall.opened_at}" if stall and stall.opened_at else ""
    return f"Task: {subject(lesson)}. You opened `{lesson.file}`{when}. No edit yet. {NEXT}"


def _stalled(lesson: Lesson) -> TrainingRow | None:
    stall = lesson.stall
    if stall is None:
        return None
    question = f"Task: {subject(lesson)}, {stall.step_limit}-step limit. {_state(stall)} {NEXT}"
    answer = f"{_turn(stall)} {directive(lesson)}"
    return TrainingRow(lesson.lesson_id, "stalled", _chat(AGENT_SYSTEM, question, answer))


def _state(stall: Stall) -> str:
    """The stalled run's state in present tense; only steps and counts the run really had."""
    if stall.wrong_file:
        return f"You have edited `{stall.wrong_file}` at step {stall.first_edit}."
    if stall.opened_at is None:
        return (
            f"You have not opened `{stall.file}`; you have written "
            f"{stall.scratch_scripts} scratch scripts and made no edit."
        )
    if stall.first_edit:
        return (
            f"You opened `{stall.file}` at step {stall.opened_at}; it is step "
            f"{stall.first_edit - 1} and you have not edited it."
        )
    return (
        f"You have read `{stall.file}` {stall.reads} times, written "
        f"{stall.scratch_scripts} scratch scripts and made no edit."
    )


def _turn(stall: Stall) -> str:
    if stall.wrong_file:
        return f"The fix does not belong in `{stall.wrong_file}`."
    return "Stop exploring."


def corrected_actions(lesson: Lesson) -> list[TrainingRow]:
    """Situation to corrected action: the file just opened, and the run's own stall if any."""
    if lesson.source == LessonSource.REPO_HABIT:
        answer = f"{lesson.resolved} Run `{lesson.check}`."
        row = _chat(AGENT_SYSTEM, f"{lesson.title} {NEXT}", answer)
        return [TrainingRow(lesson.lesson_id, "habit", row)]
    opened = TrainingRow(
        lesson.lesson_id, "opened", _chat(AGENT_SYSTEM, _opened(lesson), directive(lesson))
    )
    stalled = _stalled(lesson)
    return [opened, stalled] if stalled else [opened]


def training_rows(lesson: Lesson) -> list[TrainingRow]:
    """Every row of one lesson: self-study first, then corrected actions."""
    return self_study(lesson) + corrected_actions(lesson)


def held_out_question(lesson: Lesson) -> dict[str, str]:
    """One recall question per lesson in a wording no training row uses."""
    text = f"Before I start on {subject(lesson)} in the sqlglot repo, what should I know?"
    return {"question_id": f"{lesson.lesson_id}-q", "lesson_id": lesson.lesson_id, "text": text}
