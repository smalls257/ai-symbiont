"""The coding domain plugin: sqlglot tasks through CAL2, graded by each task's hidden tests.

Attempts and evaluation run CAL2 (`--fixed-runs 1`, `--model` for a round's Glimmer); harvest
reuses the general-lessons builder over the plain logs plus the loop's training logs, never an
evaluation log. Habit cards close on own verified passes, repo cards on training-task upstream
fixes; every text is scanned against held-out gold lines. Route A is not wired for CAL2.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import general_habits as habits
from attempts import Attempt, Outcome, Split, mined_ids
from coding_runs import (
    PLAIN_GLIMMER,
    CodingPaths,
    attempt_log,
    attempts_from_log,
    cal2_command,
    mined_evidence,
    slug,
)
from domain import Harvest
from general_evidence import Evidence, SourceTask, load_evidence
from general_leakage import conventions, leaking_keys, name_hits, specific_names
from general_lesson import GeneralLesson, LessonKind
from general_places import task_place_kinds
from general_rows import action_rows
from general_runs import PLAIN_LOGS, PlainRun, plain_runs
from general_split import evaluation_ids
from learners import RouteNotWiredError
from loop_cards import LessonCard, Resolution, ResolutionSource
from runner import CommandRunner
from sqlglot_leakage import gold_lines, leaks_by_task
from sqlglot_rows import MEMORY_SYSTEM
from training_plan import Row
from utility import AblationPair, Mark

LOOP_DIR = "loop/coding-sqlglot"  # under the CAL2 workdir, beside the plain logs
BATCH = 24  # training tasks per round (estimate.py)
ABLATION_LESSONS, ABLATION_TASKS = 2, 3  # with-card runs per round: 6
MAX_ROW_CHARS = 2048  # about 512 tokens: Route B's row check and the post-stall cap
EARLY_VIEW = habits.EARLY_VIEW

Shows = Callable[[PlainRun, habits.Gold], bool]


def _opened_fix_early(run: PlainRun, gold: habits.Gold) -> bool:
    views = [run.facts.first_view[f] for f in gold.get(run.task, ()) if f in run.facts.first_view]
    return bool(views) and min(views) <= EARLY_VIEW


def _ran_tests(run: PlainRun, gold: habits.Gold) -> bool:
    return habits.whole_suite(run, gold) or habits.targeted_test(run, gold)


def _always(_run: PlainRun, _gold: habits.Gold) -> bool:
    return True


def _scratched(run: PlainRun, _gold: habits.Gold) -> bool:
    return run.facts.scratch_scripts > 0


def _edited(run: PlainRun, _gold: habits.Gold) -> bool:
    return bool(run.facts.edited)


def _test_passed(run: PlainRun, _gold: habits.Gold) -> bool:
    return run.facts.verified_test is not None


def _untargeted(run: PlainRun, gold: habits.Gold) -> bool:
    return not habits.targeted_test(run, gold)


# Habit card id -> (its situation arose, its mistake happened), on one graded run.
HABIT_MARKS: dict[str, tuple[Shows, Shows]] = {
    "habit-edit-once-found": (_opened_fix_early, habits.never_edited),
    "habit-repro-once": (_scratched, habits.scratch_not_edit),
    "habit-budget-the-steps": (_always, habits.late_first_edit),
    "habit-check-the-layer": (_edited, habits.wrong_layer),
    "habit-submit-when-green": (_test_passed, habits.passing_not_submitted),
    "habit-one-test-module": (_ran_tests, _untargeted),
}


class MissingTrajectoryError(FileNotFoundError):
    """A graded attempt whose trajectory cannot be read; it is never marked not applicable."""


@dataclass
class CodingSqlglot:
    """The coding-sqlglot domain."""

    paths: CodingPaths
    runner: CommandRunner
    name: str = "coding-sqlglot"
    plain_model: str = PLAIN_GLIMMER
    subject: str = "In sqlglot"
    memory_system: str = MEMORY_SYSTEM
    max_row_chars: int = MAX_ROW_CHARS
    evidence: Evidence | None = None  # mined only: what lessons are built from
    lessons: dict[str, GeneralLesson] = field(default_factory=dict)
    tasks: dict[str, SourceTask] = field(default_factory=dict)  # every training task, for marks
    facts: dict[str, PlainRun] = field(default_factory=dict)  # attempt id -> run, for marks
    loaded_logs: set[str] = field(default_factory=set)

    def held_out(self) -> frozenset[str]:
        """The 18 tasks of results/general-split.json."""
        return evaluation_ids(self.paths.split)

    def training_batch(self, round_index: int) -> tuple[str, ...]:
        """BATCH pool tasks outside the split, a new window each round."""
        pool = json.loads((self.paths.workdir / "data" / "pool.json").read_text())["pool"]
        held = self.held_out()
        ids = sorted(e["instance_id"] for e in pool if e["instance_id"] not in held)
        start = round_index * BATCH
        return tuple(ids[(start + i) % len(ids)] for i in range(min(BATCH, len(ids))))

    def attempt(
        self, model: str, tasks: Sequence[str], round_index: int, trained: frozenset[str]
    ) -> list[Attempt]:
        """CAL2 on the training tasks; one graded run each."""
        runs_dir = f"{LOOP_DIR}/r{round_index}-{slug(model)}"
        self._drive(model, tasks, runs_dir, None)
        return attempts_from_log(self.paths.workdir / runs_dir, runs_dir, tasks, model,
                                 (round_index, Split.TRAINING, trained))  # fmt: skip

    def evaluate(self, model: str, round_index: int, trained: frozenset[str]) -> list[Attempt]:
        """CAL2 on every held-out task; its log is never a harvest source."""
        runs_dir = f"{LOOP_DIR}/eval-r{round_index}-{slug(model)}"
        tasks = sorted(self.held_out())
        self._drive(model, tasks, runs_dir, None)
        return attempts_from_log(self.paths.workdir / runs_dir, runs_dir, tasks, model,
                                 (round_index, Split.HELD_OUT, trained))  # fmt: skip

    def _drive(self, model: str, tasks: Sequence[str], runs_dir: str, lessons: Path | None) -> None:
        if model.startswith("user-model+"):
            raise RouteNotWiredError("CAL2 runs Glimmer by name; Route A notes are not wired")
        where = self.paths.workdir / runs_dir
        where.mkdir(parents=True, exist_ok=True)
        (where / "tasks.jsonl").write_text("".join(json.dumps({"instance_id": t}) + "\n"
                                                   for t in tasks))  # fmt: skip
        self.runner.run(cal2_command(self.paths, model, runs_dir, lessons), self.paths.workdir)

    def harvest(
        self,
        attempts: Sequence[Attempt],
        known: Mapping[str, LessonCard],
        quotas: Mapping[str, int],
    ) -> Harvest:
        """General lessons from allow-listed attempts and plain history off the baseline half."""
        from build_general_lessons import lessons_from

        allowed = mined_ids(attempts)
        logs = list(PLAIN_LOGS) + sorted({attempt_log(a) for a in attempts})
        loaded = load_evidence(self.paths.workdir, self.paths.split, self.paths.clone, logs)
        self.tasks = dict(loaded.tasks)
        self.evidence = mined_evidence(loaded, allowed)
        self.lessons = {x.lesson_id: x for x in lessons_from(self.evidence)}
        cards = [self._card(x, known.get(x.lesson_id), attempts) for x in self.lessons.values()]
        return Harvest(tuple(cards), self._action_rows(), (), sum(c.is_open for c in cards))

    def _card(
        self, lesson: GeneralLesson, earlier: LessonCard | None, attempts: Sequence[Attempt]
    ) -> LessonCard:
        card = LessonCard(
            lesson.lesson_id, self.name, str(lesson.kind), lesson.situation, lesson.happened,
            lesson.check, lesson.source_tasks,
            earlier.first_round if earlier else max((a.round_index for a in attempts), default=0),
        )  # fmt: skip
        proof = self._proof(lesson, card, attempts)
        return card.resolved_by(proof, lesson.resolved) if proof else card

    def _proof(
        self, lesson: GeneralLesson, card: LessonCard, attempts: Sequence[Attempt]
    ) -> Resolution | None:
        """Upstream fixes for repo knowledge; graded passes that avoided the mistake for habits."""
        if lesson.kind is not LessonKind.HABIT:
            fixes = tuple(sorted(set(lesson.source_tasks) - self.held_out()))
            return Resolution(ResolutionSource.UPSTREAM_FIX, fixes) if fixes else None
        passes = tuple(a.attempt_id for a in attempts
                       if a.passed and self.mark(card, a) is Mark.AVOIDED)  # fmt: skip
        return Resolution(ResolutionSource.OWN_VERIFIED_SUCCESS, passes[:10]) if passes else None

    def _action_rows(self) -> dict[str, list[Row]]:
        """Corrected-action rows from stalled runs, minus any naming a held-out fix's code word."""
        assert self.evidence is not None
        tasks = self.evidence.tasks
        gold = {t.task: t.gold_files for t in tasks.values()}
        rows = action_rows(self.evidence.runs, tasks, gold)
        keyed = {str(i): "\n".join(m["content"] for m in r.messages) for i, r in enumerate(rows)}
        common = conventions(t.gold_patch for t in tasks.values())
        dropped = leaking_keys(keyed, self.evidence.evaluation_patches, common)
        found: dict[str, list[Row]] = {}
        for i, row in enumerate(rows):
            if str(i) not in dropped:
                found.setdefault(row.lesson_id, []).append(
                    Row(row.lesson_id, "situation", tuple(row.messages))
                )
        return found

    def mark(self, card: LessonCard, attempt: Attempt) -> Mark:
        """Habits by their run predicates; repo knowledge by the place kinds the fix lands in."""
        if not self.tasks:
            raise RuntimeError("mark before harvest: the task places are loaded by harvest")
        run = self._run_of(attempt)
        gold = {t.task: t.gold_files for t in self.tasks.values()}
        if card.lesson_id in HABIT_MARKS:
            return _habit_mark(card.lesson_id, run, gold)
        task = self.tasks.get(run.task)
        lesson = self.lessons.get(card.lesson_id)
        if task is None or lesson is None:
            return Mark.NOT_APPLICABLE
        kinds = {str(kind) for kind in task_place_kinds(task.places)}
        if not kinds & set(lesson.teaches):
            return Mark.NOT_APPLICABLE
        missed = not set(run.facts.edited) & set(task.gold_files)
        return Mark.REPEATED if missed else Mark.AVOIDED

    def _run_of(self, attempt: Attempt) -> PlainRun:
        """The graded run's facts, read from its log once; a missing trajectory raises."""
        log = attempt_log(attempt)
        if log not in self.loaded_logs:
            for run in plain_runs(self.paths.workdir, [log]):
                self.facts[f"{run.facts.run_id}/{run.task}"] = run
            self.loaded_logs.add(log)
        if attempt.attempt_id not in self.facts:
            raise MissingTrajectoryError(f"no graded trajectory for {attempt.attempt_id}")
        return self.facts[attempt.attempt_id]

    def ablate(
        self, model: str, cards: Sequence[LessonCard], attempts: Sequence[Attempt]
    ) -> list[AblationPair]:
        """The round's model with the card in the prompt on a few applicable tasks; the round's
        own attempt on each task is the without side."""
        trained = [c for c in cards if any(c.lesson_id in a.trained_lessons for a in attempts)]
        pairs: list[AblationPair] = []
        for card in trained[:ABLATION_LESSONS]:
            sample = [a for a in attempts if self.mark(card, a) is not Mark.NOT_APPLICABLE]
            if sample:
                pairs += self._ablate_one(model, card, sample[:ABLATION_TASKS])
        return pairs

    def _ablate_one(
        self, model: str, card: LessonCard, sample: Sequence[Attempt]
    ) -> list[AblationPair]:
        runs_dir = f"{LOOP_DIR}/ablate-r{sample[0].round_index}-{card.lesson_id}"
        card_file = self.paths.workdir / runs_dir / "card.json"
        card_file.parent.mkdir(parents=True, exist_ok=True)
        card_file.write_text(json.dumps({a.task_id: card.text() for a in sample}))
        tasks = [a.task_id for a in sample]
        self._drive(model, tasks, runs_dir, card_file)
        context = (sample[0].round_index, Split.TRAINING, frozenset[str]())
        with_card = attempts_from_log(self.paths.workdir / runs_dir, runs_dir, tasks, model,
                                      context)  # fmt: skip
        return [
            AblationPair(card.lesson_id, w.task_id, w.passed, a.passed)
            for w, a in zip(with_card, sample, strict=True)
            if w.outcome is not Outcome.UNGRADED
        ]

    def leak_hits(self, texts: Mapping[str, str]) -> dict[str, list[str]]:
        """Held-out gold lines and specific names, per text."""
        if self.evidence is None:
            raise RuntimeError("leak check before harvest: the gold patches are loaded by harvest")
        patches = self.evidence.evaluation_patches
        gold = {task: gold_lines(patch) for task, patch in patches.items()}
        common = conventions(t.gold_patch for t in self.evidence.tasks.values())
        names = specific_names(patches, common)
        hits = {}
        for key, text in texts.items():
            found = sorted(leaks_by_task(text, gold)) + sorted(name_hits(text, names))
            if found:
                hits[key] = found
        return hits


def _habit_mark(card_id: str, run: PlainRun, gold: habits.Gold) -> Mark:
    """A habit card's mark on one run, from its (situation, mistake) predicates."""
    arose, mistake = HABIT_MARKS[card_id]
    if not arose(run, gold):
        return Mark.NOT_APPLICABLE
    return Mark.REPEATED if mistake(run, gold) else Mark.AVOIDED
