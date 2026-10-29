"""Route B training rows for a personal Glimmer LoRA: LCAP's lessons as chat rows Glimmer reads.

Each lesson keeps LCAP's six rows (self-study Q&A and situation to corrected action) and adds two
rows that answer with the lesson card: what happened, how it was resolved, the check to run. Every
detail in a card is quoted from the lesson's fields, never paraphrased. Pure: lessons in, rows out.
"""

from lessons import Lesson
from questions import SYSTEM as MEMORY_SYSTEM
from questions import held_out_questions, lessons_prompt, training_messages

# Glimmer's chat template appends "Reasoning strength: high." unless the system turn names a
# strength; answers go straight to the user channel, so the reasoning budget is set to low.
REASONING = "Reasoning strength: low."
SYSTEM = f"{MEMORY_SYSTEM}\n\n{REASONING}"

Row = dict[str, list[dict[str, str]]]


def card(lesson: Lesson) -> str:
    """The lesson as one line: what happened, how it was resolved, the check to run."""
    added = " ".join(f"`{token}`" for token in lesson.added)
    return (
        f"What happened: in {lesson.repo}, `{lesson.failed}` failed with {lesson.error}. "
        f"How it was resolved: `{lesson.fix}` exited 0. "
        f"The check to run: before running {lesson.program} on {lesson.file}, "
        f"make sure the command has {added}."
    )


def _card_questions(lesson: Lesson) -> list[str]:
    where = f"{lesson.program} on {lesson.file}"
    return [
        f"What is the lesson from {where} in {lesson.repo}: what happened, how was it resolved, "
        "and what should I check?",
        f"`{lesson.failed}` in {lesson.repo}: what happened last time, what fixed it, "
        "and what is the check to run?",
    ]


def training_rows(lesson: Lesson) -> list[Row]:
    """LCAP's six rows plus two lesson-card rows, all under Glimmer's system turn."""
    rows = [_with_system(row) for row in training_messages(lesson)]
    rows += [_chat(question, card(lesson)) for question in _card_questions(lesson)]
    _refuse_held_out_wording(lesson, rows)
    return rows


def ceiling_system(lessons: list[Lesson]) -> str:
    """The ceiling arm's system turn: every lesson of the set in the prompt."""
    return f"{lessons_prompt(lessons)}\n\n{REASONING}"


def _with_system(row: Row) -> Row:
    rest = [message for message in row["messages"] if message["role"] != "system"]
    return {"messages": [{"role": "system", "content": SYSTEM}, *rest]}


def _chat(question: str, answer: str) -> Row:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


def _refuse_held_out_wording(lesson: Lesson, rows: list[Row]) -> None:
    asked = {question.text for question in held_out_questions(lesson)}
    trained = {message["content"] for row in rows for message in row["messages"]}
    leaked = asked & trained
    if leaked:
        raise ValueError(f"lesson {lesson.lesson_id}: a held-out question is a training prompt")
