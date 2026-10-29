"""Process habits from Glimmer's plain sqlglot runs, each counted across non-evaluation tasks.

A habit is kept only when several tasks show it; its text says what Glimmer did, what the runs
that solved did instead, and one check that applies to any bug. Pure: runs and gold files in.
"""

import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from general_lesson import GeneralLesson
from general_runs import PlainRun
from sqlglot_runs import Trap

EARLY_VIEW = 15  # the fix file was opened by this step (glimmer-analysis.md: steps 2-12)
MANY_SCRATCH = 5  # scratch scripts (glimmer-analysis.md section 3 threshold)
LATE_EDIT = 30  # first edit after this step of 50 leaves too few steps (solved: median 12.5)
MIN_TASKS = 3  # a habit seen in fewer tasks is anecdote, not a habit
WHOLE_SUITE = re.compile(
    r"unittest\s+discover|python3?\s+-m\s+unittest\s*($|[;&|2>])|pytest\s*($|[;&|])"
    r"|pytest\s+(-\S+\s+)*tests/?\s*($|[;&|])"
)
TARGETED = re.compile(r"python3?\s+-m\s+unittest\s+(-\S+\s+)*tests\.")
Gold = Mapping[str, Sequence[str]]  # task id to its gold source files


@dataclass(frozen=True)
class HabitCount:
    """How many runs and tasks show a pattern, and how the runs that show it ended."""

    runs: int
    tasks: int
    solved: int
    of_runs: int
    solved_without: int
    runs_without: int

    def support(self) -> dict[str, int]:
        """The counts as a manifest entry."""
        return self.__dict__.copy()


def _gold_view(run: PlainRun, gold: Gold) -> int | None:
    views = [run.facts.first_view[f] for f in gold.get(run.task, ()) if f in run.facts.first_view]
    return min(views) if views else None


def found_not_edited(run: PlainRun, gold: Gold) -> bool:
    """Opened the file the upstream fix changed by EARLY_VIEW, and never edited any source."""
    view = _gold_view(run, gold)
    return view is not None and view <= EARLY_VIEW and run.facts.first_edit is None


def never_edited(run: PlainRun, _gold: Gold) -> bool:
    """No source edit in the whole run."""
    return run.facts.first_edit is None


def scratch_not_edit(run: PlainRun, _gold: Gold) -> bool:
    """Many scratch scripts, no source edit."""
    return run.facts.scratch_scripts >= MANY_SCRATCH and run.facts.first_edit is None


def late_first_edit(run: PlainRun, _gold: Gold) -> bool:
    """The first source edit came after LATE_EDIT steps."""
    return run.facts.first_edit is not None and run.facts.first_edit > LATE_EDIT


def wrong_layer(run: PlainRun, gold: Gold) -> bool:
    """Edited source files, none of them a file the upstream fix changed."""
    edited = set(run.facts.edited)
    return bool(edited) and not edited & set(gold.get(run.task, ()))


def passing_not_submitted(run: PlainRun, _gold: Gold) -> bool:
    """A targeted test passed after an edit, and the run still hit the cap."""
    return run.facts.verified_test is not None and not run.submitted


def whole_suite(run: PlainRun, _gold: Gold) -> bool:
    """Ran the whole test suite at least once."""
    return any(WHOLE_SUITE.search(command) for command in run.commands)


def targeted_test(run: PlainRun, _gold: Gold) -> bool:
    """Ran one or a few named unittest modules at least once."""
    return any(TARGETED.search(command) for command in run.commands)


Shows = Callable[[PlainRun, Gold], bool]


def count(runs: Sequence[PlainRun], gold: Gold, shows: Shows) -> HabitCount:
    """Count one pattern over the runs."""
    showing = [run for run in runs if shows(run, gold)]
    rest = [run for run in runs if not shows(run, gold)]
    return HabitCount(
        runs=len(showing),
        tasks=len({run.task for run in showing}),
        solved=sum(run.resolved for run in showing),
        of_runs=len(runs),
        solved_without=sum(run.resolved for run in rest),
        runs_without=len(rest),
    )


def view_to_edit_gap(runs: Sequence[PlainRun], gold: Gold) -> int:
    """Median steps from opening the fix file to the first edit, in solved runs."""
    gaps = [
        run.facts.first_edit - view
        for run in runs
        if run.resolved and run.facts.first_edit and (view := _gold_view(run, gold)) is not None
    ]
    return round(statistics.median(gaps)) if gaps else 0


def _edit_bucket(run: PlainRun) -> str:
    edit = run.facts.first_edit
    if not edit:
        return "never"
    return "early" if edit <= LATE_EDIT else "late"


def edit_timing(runs: Sequence[PlainRun]) -> dict[str, int]:
    """At cap 50: solved and total runs with the first edit by LATE_EDIT, after it, or never."""
    found = {
        f"{name}_{what}": 0 for name in ("early", "late", "never") for what in ("runs", "solved")
    }
    for run in runs:
        if run.step_limit != 50:
            continue
        bucket = _edit_bucket(run)
        found[f"{bucket}_runs"] += 1
        found[f"{bucket}_solved"] += run.resolved
    return found


def edit_to_end(runs: Sequence[PlainRun]) -> int:
    """Median steps from the first edit to the end of a solved run."""
    gaps = [
        run.facts.steps - run.facts.first_edit
        for run in runs
        if run.resolved and run.facts.first_edit
    ]
    return round(statistics.median(gaps)) if gaps else 0


def submissions(runs: Sequence[PlainRun]) -> dict[str, int]:
    """Submitted runs and how many of them resolved."""
    sent = [run for run in runs if run.submitted]
    return {"submitted": len(sent), "submitted_solved": sum(run.resolved for run in sent)}


def trap_counts(runs: Sequence[PlainRun]) -> dict[str, int]:
    """Runs that hit each tool trap of the task image."""
    return {str(trap): sum(trap in run.facts.traps for run in runs) for trap in Trap}


def supported(lessons: Sequence[GeneralLesson]) -> list[GeneralLesson]:
    """Only habits that several tasks show."""
    return [lesson for lesson in lessons if lesson.support.get("tasks", MIN_TASKS) >= MIN_TASKS]
