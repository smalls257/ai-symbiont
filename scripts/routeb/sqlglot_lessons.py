"""Lessons for the sqlglot Route B adapter: Glimmer's own sqlglot runs, as three-part lessons.

Each lesson says what happened, how it was resolved and the check to run, and keeps the state a
failed run stalled in so a training row can put Glimmer back into that state with the corrected
action. Glimmer already finds the right file (capability-pairs.md), so a lesson names the construct
inside it and the test that proved the fix; a lesson that cannot name both is dropped and counted
by reason, never filled with a guess. Pure: run facts, places and curated text in, lessons out.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlglot_places import MODULE_LEVEL, Place
from sqlglot_runs import RunFacts

MAX_TITLE_CHARS = 100  # one line of a ~130-token row; longer issue titles are cut at a word


class LessonSource(StrEnum):
    """Where a lesson's resolution comes from."""

    OWN_SOLVE = "own-solve"  # a solved Glimmer run of the task; its failed runs give the stall
    OWN_FAILURE = "own-failure"  # never solved by Glimmer; the place is the public upstream fix
    PAIR = "capability-pair"  # an earlier task's lesson phrased for a harder, later task
    REPO_HABIT = "repo-habit"  # a tool trap of the task image, counted across all runs


class Link(StrEnum):
    """How a lesson relates to an evaluation task."""

    SAME_TASK = "same-task"  # Tier 1: the eval task's own earlier solved run
    PAIR_LESSON = "pair-lesson"  # Tier 2: the A-to-B lesson written for this task
    PAIR_SOURCE = "pair-source"  # the A task a Tier 2 pair lesson is drawn from


def _scripts(count: int) -> str:
    return f"{count} scratch script" + ("" if count == 1 else "s")


@dataclass(frozen=True)
class Stall:
    """Where a failed run spent its steps: the state a behavior row puts Glimmer back into."""

    run_id: str
    steps: int
    step_limit: int
    file: str
    opened_at: int | None
    reads: int
    scratch_scripts: int
    first_edit: int | None
    wrong_file: str | None

    def prose(self) -> str:
        """One clause, in the second person, of what the run did."""
        if self.wrong_file:
            return (
                f"you edited `{self.wrong_file}` at step {self.first_edit}, but the fix did not "
                f"belong there, and you hit the {self.step_limit}-step cap"
            )
        if self.opened_at is None:
            return f"you never opened `{self.file}` and hit the {self.step_limit}-step cap"
        if self.first_edit is None:
            return (
                f"you opened `{self.file}` at step {self.opened_at}, read it {self.reads} times, "
                f"wrote {_scripts(self.scratch_scripts)} and never edited it before the "
                f"{self.step_limit}-step cap"
            )
        return (
            f"you opened `{self.file}` at step {self.opened_at} but first edited it at step "
            f"{self.first_edit} of {self.step_limit}, too late to test and submit"
        )


@dataclass(frozen=True)
class Lesson:
    """One three-part lesson, its source runs and the evaluation tasks it is meant for."""

    lesson_id: str
    source: LessonSource
    task: str | None
    runs: tuple[str, ...]
    title: str
    happened: str
    resolved: str
    check: str
    file: str
    place: str
    stall: Stall | None = None
    links: tuple[tuple[str, Link], ...] = field(default=())

    def card(self) -> str:
        """What happened, how it was resolved, the check to run: the lesson in one paragraph."""
        return (
            f"What happened: {self.happened} How it was resolved: {self.resolved} "
            f"The check to run: `{self.check}`."
        )


@dataclass(frozen=True)
class TaskEvidence:
    """Everything known about one attempted task, from its public row and Glimmer's runs."""

    task: str
    title: str
    created: str
    test: str
    gold_places: tuple[Place, ...]
    runs: tuple[RunFacts, ...]
    solved_places: tuple[Place, ...] = ()


def issue_title(problem_statement: str) -> str:
    """The issue's first line, markdown heading marks removed, cut at a word boundary."""
    first = next((line for line in problem_statement.splitlines() if line.strip()), "")
    title = " ".join(first.lstrip("#").split()).rstrip(".")
    if len(title) <= MAX_TITLE_CHARS:
        return title
    return title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] + " ..."


def test_command(fail_to_pass: Sequence[str]) -> str:
    """`python -m unittest` over the modules of the task's failing tests."""
    modules = [re.sub(r"\.py$", "", test.split("::")[0]).replace("/", ".") for test in fail_to_pass]
    found = [module for module in dict.fromkeys(modules) if module.startswith("tests")]
    if not found:
        raise ValueError(f"no unittest module in the failing tests {list(fail_to_pass)[:3]}")
    return "python -m unittest " + " ".join(found)


def places_prose(found: Sequence[Place]) -> str:
    """The places grouped by file, at most two files; module-level code is named by its file."""
    files = list(dict.fromkeys(place.file for place in found))
    named = [_in_file(file, [p.name for p in found if p.file == file]) for file in files[:2]]
    more = f" (and {len(files) - 2} more files)" if len(files) > 2 else ""
    return " and ".join(named) + more


def _in_file(file: str, names: Sequence[str]) -> str:
    constructs = [f"`{name}`" for name in names if name != MODULE_LEVEL]
    if not constructs:
        return f"module-level code in `{file}`"
    extra = " and module-level code" if len(constructs) < len(names) else ""
    return f"{', '.join(constructs[:3])}{extra} in `{file}`"


def primary(found: Sequence[Place]) -> Place:
    """The first place that is not module-level code, else the first place."""
    return next((place for place in found if place.name != MODULE_LEVEL), found[0])


def stall_of(run: RunFacts, fix_files: Sequence[str]) -> Stall:
    """The state a failed run stalled in, judged against the files the fix went in."""
    viewed = [path for path in fix_files if path in run.first_view]
    file = viewed[0] if viewed else fix_files[0]
    wrong = next((path for path in run.edited if path not in fix_files), None)
    return Stall(
        run_id=run.run_id,
        steps=run.steps,
        step_limit=run.step_limit,
        file=file,
        opened_at=run.first_view.get(file),
        reads=run.rereads.get(file, 0) + (file in run.first_view),
        scratch_scripts=run.scratch_scripts,
        first_edit=run.first_edit,
        wrong_file=wrong,
    )


def first_stall(evidence: TaskEvidence, fix: Sequence[Place]) -> Stall | None:
    """The stall of the task's first failed run, when it has one."""
    failed = [run for run in evidence.runs if not run.resolved]
    files = list(dict.fromkeys(place.file for place in fix))
    return stall_of(failed[0], files) if failed and files else None


def _ran_out(evidence: TaskEvidence, stall: Stall | None) -> str:
    if stall is None:
        return ""
    failed = sum(not run.resolved for run in evidence.runs)
    return f" In {failed} of {len(evidence.runs)} runs you did not finish: {stall.prose()}."


def own_solve(evidence: TaskEvidence, lesson_id: str) -> Lesson:
    """A lesson from Glimmer's first solved run of the task, with the stall of a failed run."""
    solved = next(run for run in evidence.runs if run.resolved)
    fix = evidence.solved_places or evidence.gold_places
    stall = first_stall(evidence, fix)
    check = solved.verified_test or evidence.test
    return Lesson(
        lesson_id=lesson_id,
        source=LessonSource.OWN_SOLVE,
        task=evidence.task,
        runs=tuple(run.run_id for run in evidence.runs),
        title=evidence.title,
        happened=f'Issue "{evidence.title}".{_ran_out(evidence, stall)}',
        resolved=(
            f"Your passing run edited {places_prose(fix)}, first edit at step "
            f"{solved.first_edit} of {solved.step_limit}, and `{check}` passed."
        ),
        check=check,
        file=primary(fix).file,
        place=f"`{primary(fix).name}`",
        stall=stall,
    )


def own_failure(evidence: TaskEvidence, lesson_id: str) -> Lesson:
    """A lesson from runs that never solved the task; the place is the public upstream fix."""
    fix = evidence.gold_places
    stall = first_stall(evidence, fix)
    return Lesson(
        lesson_id=lesson_id,
        source=LessonSource.OWN_FAILURE,
        task=evidence.task,
        runs=tuple(run.run_id for run in evidence.runs),
        title=evidence.title,
        happened=f'Issue "{evidence.title}".{_ran_out(evidence, stall)}',
        resolved=f"The upstream fix went in {places_prose(fix)}.",
        check=evidence.test,
        file=primary(fix).file,
        place=f"`{primary(fix).name}`",
        stall=stall,
    )


def curated(evidence: TaskEvidence, lesson_id: str, parts: Mapping[str, str]) -> Lesson:
    """A Tier 1 lesson whose three parts were written by hand from the task's solved run."""
    fix = evidence.solved_places or evidence.gold_places
    return Lesson(
        lesson_id=lesson_id,
        source=LessonSource.OWN_SOLVE,
        task=evidence.task,
        runs=tuple(run.run_id for run in evidence.runs),
        title=evidence.title,
        happened=parts["happened"],
        resolved=parts["resolved"],
        check=parts["check"],
        file=parts["file"],
        place=parts["place"],
        stall=first_stall(evidence, fix),
        links=((evidence.task, Link.SAME_TASK),),
    )


def pair(target: str, lesson_id: str, parts: Mapping, source_runs: Sequence[str]) -> Lesson:
    """A Tier 2 lesson: an earlier task's convention, phrased without the target task's text."""
    return Lesson(
        lesson_id=lesson_id,
        source=LessonSource.PAIR,
        task=None,
        runs=tuple(source_runs),
        title=parts["situation"],
        happened=parts["happened"],
        resolved=parts["resolved"],
        check=parts["check"],
        file=parts["file"],
        place=parts["place"],
        links=((target, Link.PAIR_LESSON),),
    )
