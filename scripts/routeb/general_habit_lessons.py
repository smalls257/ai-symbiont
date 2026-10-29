"""The habit lessons, worded for any sqlglot bug or feature, each carrying its measured counts.

Every number in a sentence comes from the counts passed in; nothing names a task or its fix.
Pure.
"""

from collections.abc import Sequence

import general_habits as habits
from general_lesson import GeneralLesson, LessonKind
from general_runs import PlainRun

UNITTEST = "python -m unittest tests.dialects.test_<dialect>"


def _tasks(runs: Sequence[PlainRun], gold: habits.Gold, shows: habits.Shows) -> tuple[str, ...]:
    return tuple(sorted({run.task for run in runs if shows(run, gold)}))


def edit_once_found(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """Found the code, kept reading: the dominant failure."""
    found = habits.count(runs, gold, habits.found_not_edited)
    never = habits.count(runs, gold, habits.never_edited)
    timing = habits.edit_timing(runs)
    return GeneralLesson(
        lesson_id="habit-edit-once-found",
        kind=LessonKind.HABIT,
        situation=(
            "You have opened the file whose code produces the wrong output and keep reading it."
        ),
        happened=(
            "Runs that never edited a source file never solved the task, though most of them had "
            "already opened the file the fix belonged in."
        ),
        resolved=(
            "Runs that made their first edit early, soon after finding the code, mostly solved; "
            "runs that edited late mostly ran out of steps."
        ),
        check=(
            "once one read shows the code that builds the wrong output, make the smallest edit "
            f"there, then run `{UNITTEST}`."
        ),
        support=found.support() | timing | {"never_edited_runs": never.runs},
        source_tasks=_tasks(runs, gold, habits.never_edited),
    )


def repro_once(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """Scratch scripts in place of an edit."""
    found = habits.count(runs, gold, habits.scratch_not_edit)
    return GeneralLesson(
        lesson_id="habit-repro-once",
        kind=LessonKind.HABIT,
        situation="You are about to write another scratch script to reproduce the issue.",
        happened=(
            "Runs that kept writing new scratch scripts to reproduce the issue never got to an "
            "edit and never solved."
        ),
        resolved=("Solved runs reproduced the issue with one `python -c` call and then edited."),
        check=(
            'reproduce once with `python -c "import sqlglot; print(sqlglot.transpile(SQL, '
            "read='a', write='b'))\"`, then edit; rerun the same line after the edit."
        ),
        support=found.support(),
        source_tasks=_tasks(runs, gold, habits.scratch_not_edit),
    )


def budget_the_steps(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """A late first edit leaves no room to test and submit."""
    late = habits.count(runs, gold, habits.late_first_edit)
    return GeneralLesson(
        lesson_id="habit-budget-the-steps",
        kind=LessonKind.HABIT,
        situation="Half your step budget is gone and you have not edited anything yet.",
        happened=(
            "When the first edit came late in the step budget, most runs ran out of steps before "
            "testing and submitting."
        ),
        resolved=(
            "Solved runs left room after the first edit for one test run, one fix-up and the "
            "submit."
        ),
        check=(
            "by the middle of the budget, edit your best candidate and test it rather than read on."
        ),
        support=late.support(),
        source_tasks=_tasks(runs, gold, habits.late_first_edit),
    )


def check_the_layer(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """Edited a file the fix did not belong in."""
    found = habits.count(runs, gold, habits.wrong_layer)
    return GeneralLesson(
        lesson_id="habit-check-the-layer",
        kind=LessonKind.HABIT,
        situation=(
            "You are about to edit a file before knowing whether reading or writing SQL is wrong."
        ),
        happened=(
            "Some runs edited only files the real fix never touched: a dialect file when the fix "
            "was shared, or the reverse."
        ),
        resolved=(
            "The wrong half is found by parsing alone: if the parsed tree is wrong the fix is in "
            "a parser or tokenizer, if the tree is right and the SQL text is wrong it is in a "
            "generator."
        ),
        check=(
            "run `python -c \"import sqlglot; print(repr(sqlglot.parse_one(SQL, read='d')))\"` "
            "before the first edit."
        ),
        support=found.support(),
        source_tasks=_tasks(runs, gold, habits.wrong_layer),
    )


def submit_when_green(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """A passing targeted test, and no submit."""
    found = habits.count(runs, gold, habits.passing_not_submitted)
    sent = habits.submissions(runs)
    return GeneralLesson(
        lesson_id="habit-submit-when-green",
        kind=LessonKind.HABIT,
        situation="Your edit is in and the targeted test module passes.",
        happened=(
            "Some runs had a passing targeted test after the edit and kept working until the "
            "step cap, so nothing was submitted."
        ),
        resolved=("A submitted fix that passes its test module is almost always accepted."),
        check="when the dialect's test module passes and `git diff` shows only your fix, submit.",
        support=found.support() | sent,
        source_tasks=_tasks(runs, gold, habits.passing_not_submitted),
    )


def one_test_module(runs: Sequence[PlainRun], gold: habits.Gold) -> GeneralLesson:
    """Targeted unittest modules, and the tool traps of the task image."""
    found = habits.count(runs, gold, habits.targeted_test)
    traps = habits.trap_counts(runs)
    return GeneralLesson(
        lesson_id="habit-one-test-module",
        kind=LessonKind.HABIT,
        situation="You want to run the tests.",
        happened=(
            "`pytest` is not installed, `apply_patch` is not a command, and a script run outside "
            "the repo cannot import sqlglot; each costs a step."
        ),
        resolved=(
            "Runs that ran one named unittest module were the ones that solved; whole-suite runs "
            "added nothing."
        ),
        check=f"`cd /testbed && {UNITTEST}`; edit with `sed -i` or a short python replace.",
        support=found.support() | traps,
        source_tasks=_tasks(runs, gold, habits.targeted_test),
    )


def habit_lessons(runs: Sequence[PlainRun], gold: habits.Gold) -> list[GeneralLesson]:
    """Every habit lesson that several tasks support."""
    built = [
        builder(runs, gold)
        for builder in (
            edit_once_found,
            repro_once,
            budget_the_steps,
            check_the_layer,
            submit_when_green,
            one_test_module,
        )
    ]
    return habits.supported(built)
