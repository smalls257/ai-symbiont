"""Route B training rows for the general adapter: self-study Q&A and situation to corrected action.

Q&A rows teach each general lesson under the memory turn; action rows put Glimmer back in a state
one of its own non-evaluation runs stalled in and answer with the general habit, naming the kind
of place the upstream fix used, never a line of it. Same chat format as sqlglot_rows. Pure.
"""

from collections.abc import Mapping, Sequence

import general_habits as habits
from general_evidence import SourceTask
from general_kinds import TaskKind
from general_lesson import GeneralLesson
from general_places import PlaceKind, task_place_kinds
from general_runs import PlainRun
from sqlglot_rows import AGENT_SYSTEM, MEMORY_SYSTEM, NEXT, TrainingRow, _chat

_WHERE = {
    PlaceKind.DIALECT_TRANSFORMS: "an entry of the dialect's `Generator.TRANSFORMS` map",
    PlaceKind.DIALECT_GENERATOR: "a method or type map on the dialect's `Generator`",
    PlaceKind.DIALECT_PARSER_MAP: "the dialect's `Parser.FUNCTIONS`-style map",
    PlaceKind.DIALECT_PARSER_METHOD: "a `_parse_<thing>` method on the dialect's `Parser`",
    PlaceKind.DIALECT_TOKENIZER: "the dialect's `Tokenizer.KEYWORDS`",
    PlaceKind.SHARED_PARSER: "a `Parser._parse_<thing>` method in the shared parser",
    PlaceKind.SHARED_GENERATOR: "a `<name>_sql` method in the shared generator",
    PlaceKind.EXPRESSIONS: "an expression class's `arg_types` in `sqlglot/expressions.py`",
    PlaceKind.TOKENS: "a `TokenType` in `sqlglot/tokens.py`",
}


def lesson_rows(lesson: GeneralLesson) -> list[TrainingRow]:
    """Three Q&A rows: the whole lesson, the resolution, the check."""
    about = lesson.situation.rstrip(".")
    asked = [
        ("card", f"In sqlglot: {about}. What have you learned?", lesson.card()),
        ("resolved", f"In sqlglot: {about}. What worked?", lesson.resolved),
        ("check", f"In sqlglot: {about}. Which check do you run?", f"The check: {lesson.check}"),
    ]
    return [TrainingRow(lesson.lesson_id, kind, _chat(MEMORY_SYSTEM, q, a)) for kind, q, a in asked]


def where(task: SourceTask) -> str:
    """The kind of place the fix used in its first file, as a phrase; the file when unnamed."""
    first = [place for place in task.places if place.file == task.gold_files[0]]
    kinds = [kind for kind in PlaceKind if kind in task_place_kinds(first) and kind in _WHERE]
    return _WHERE[kinds[0]] if kinds else f"`{task.gold_files[0]}`"


def _test(task: SourceTask) -> str:
    return "python -m unittest " + " ".join(task.test_modules[:2])


def _action(task: SourceTask) -> str:
    """The corrected edit: the smallest fix for a bug, the nearest example for a feature."""
    file = task.gold_files[0]
    if task.kind is TaskKind.FEATURE:
        return (
            f"this adds support, so follow the closest existing example at {where(task)} in "
            f"`{file}`, add a `validate_identity` line beside similar ones in the dialect's test "
            f"file, then run `{_test(task)}`."
        )
    return f"make the smallest edit in `{file}` at {where(task)}, then run `{_test(task)}`."


def _found_state(run: PlainRun, task: SourceTask) -> str:
    facts, file = run.facts, task.gold_files[0]
    view = min(facts.first_view[f] for f in task.gold_files if f in facts.first_view)
    reads = facts.rereads.get(file, 0) + 1
    return f"You opened `{file}` at step {view} and have read it {reads} times; no edit yet."


def _state(run: PlainRun, task: SourceTask, gold: habits.Gold) -> tuple[str, str, str] | None:
    """(habit lesson id, present-tense state, corrected action) for the run's stall, if any."""
    facts, act = run.facts, _action(task)
    if habits.passing_not_submitted(run, gold):
        state = f"`{facts.verified_test}` passes after your edit."
        return "habit-submit-when-green", state, "Check `git diff` shows only the fix, then submit."
    if habits.wrong_layer(run, gold):
        edited = facts.edited[0]
        state = f"You edited `{edited}` and the test still fails."
        layer = "Check the layer with `repr(parse_one(SQL, read='<d>'))`; the fix is not in "
        return "habit-check-the-layer", state, f"{layer}`{edited}`: {act}"
    if habits.scratch_not_edit(run, gold):
        state = f"You have written {facts.scratch_scripts} scratch scripts and made no edit."
        return "habit-repro-once", state, f"Stop writing scripts; {act}"
    if habits.found_not_edited(run, gold):
        return "habit-edit-once-found", _found_state(run, task), f"Stop reading; {act}"
    return None


def action_rows(
    runs: Sequence[PlainRun], tasks: Mapping[str, SourceTask], gold: habits.Gold
) -> list[TrainingRow]:
    """One corrected-action row per stalled non-evaluation run whose fix file is known."""
    rows = []
    for run in runs:
        task = tasks.get(run.task)
        stall = _state(run, task, gold) if task and task.gold_files else None
        if stall is None:
            continue
        lesson_id, state, action = stall
        question = (
            f'Task: the issue "{task.title[:100]}", {run.step_limit}-step limit. {state} {NEXT}'
        )
        rows.append(TrainingRow(lesson_id, "stalled", _chat(AGENT_SYSTEM, question, action)))
    return rows


def recall_question(lesson: GeneralLesson) -> dict[str, str]:
    """One held-out recall question per lesson, in a wording no training row uses."""
    when = lesson.situation[0].lower() + lesson.situation[1:]
    text = f"Before I start on a new sqlglot issue where {when} What should I keep in mind?"
    return {"question_id": f"{lesson.lesson_id}-q", "lesson_id": lesson.lesson_id, "text": text}
