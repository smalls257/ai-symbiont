"""Repo habits for the sqlglot adapter: tool traps of the task image, counted over Glimmer's runs.

`pytest`, `apply_patch` and a bare `import sqlglot` outside the repo each cost a step whenever
they are hit (glimmer-analysis.md, section 3). They hit solved and failed runs alike, so they teach
the adapter a cheap habit, not the difference between solving and not. Pure.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sqlglot_lessons import Lesson, LessonSource
from sqlglot_runs import RunFacts, Trap


@dataclass(frozen=True)
class Habit:
    """A tool trap of the task image: what the agent sees, what happened, what works instead."""

    situation: str
    what: str
    how: str
    check: str


_HABITS = {
    Trap.PYTEST_MISSING: Habit(
        "You ran `python -m pytest` on a sqlglot test file and got 'No module named pytest'.",
        "`pytest` is not installed in the sqlglot task image, so `python -m pytest` fails",
        "the tests are plain unittest modules, so run them with `python -m unittest`",
        "python -m unittest tests.test_parser",
    ),
    Trap.APPLY_PATCH_MISSING: Habit(
        "You tried `apply_patch` on a sqlglot source file and got 'command not found'.",
        "`apply_patch` is not a command in the sqlglot task image",
        "edit the file in place with a short python `str.replace` or `sed -i`, then check it",
        "git diff",
    ),
    Trap.SQLGLOT_NOT_IMPORTABLE: Habit(
        "You ran a python script outside the repo and got 'No module named sqlglot'.",
        "a script run outside the repo failed with 'No module named sqlglot'",
        "run it from `/testbed` or with `PYTHONPATH=/testbed`",
        "cd /testbed && python -c 'import sqlglot'",
    ),
}


def habits(runs: Sequence[RunFacts]) -> list[Lesson]:
    """One lesson per tool trap that Glimmer hit in at least one run, with the measured count."""
    hit: Counter[Trap] = Counter(trap for run in runs for trap in run.traps)
    return [_habit(trap, hit[trap], len(runs)) for trap in _HABITS if hit[trap]]


def _habit(trap: Trap, hits: int, total: int) -> Lesson:
    habit = _HABITS[trap]
    return Lesson(
        lesson_id=f"habit-{trap.value}",
        source=LessonSource.REPO_HABIT,
        task=None,
        runs=(),
        title=habit.situation,
        happened=f"In {hits} of {total} sqlglot runs, {habit.what}.",
        resolved=f"The way on: {habit.how}.",
        check=habit.check,
        file="/testbed",
        place="the repository root",
    )
