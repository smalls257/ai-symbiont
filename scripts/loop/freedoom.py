"""The Freedoom domain plugin: Act 1 collector episodes, graded by reaching the exit.

A task is (level, seed). Game lessons pool into one card per (pain, move verb, check), resolved
by engine-observed progress; unresolved mistakes are only counted. Held-out levels are never
mined and their evaluation needs a frozen prereg. No lesson-in-prompt path, so no ablation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from attempts import Attempt, Outcome, Split
from build_lesson_set import read_history
from domain import Harvest
from learners import RouteNotWiredError
from loop_cards import LessonCard, Resolution, ResolutionSource
from runner import CommandRunner
from training_plan import Row
from utility import AblationPair, Mark

from symbiont.act1.game_lessons import GameLesson, lessons_from_history
from symbiont.act1.game_pains import GamePain
from symbiont.act1.glimmer import REASONING_SYSTEM_MESSAGE
from symbiont.act1.lesson_rows import Situation, training_rows
from symbiont.act1.levels import LevelSplit, require_training, split_of
from symbiont.records.schema import load_jsonl

PLAIN_GLIMMER = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
TRAINING_LEVELS = ("MAP01", "MAP02", "MAP03", "MAP05", "MAP06")  # the act1-learning protocol
EVAL_LEVELS, EVAL_SEEDS = ("MAP04", "MAP08"), (3, 4)
SEEDS_PER_ROUND = 2  # new seeds each round, so a round never replays an earlier episode
DECISIONS = 16  # act1-learning ruling: fits the Glimmer budget
SITUATIONS_PER_CHECK = 3  # situation rows per card: one habit cannot fill the set
# About 512 tokens; game prompts run to 2,530 characters, so long situation rows are dropped and
# counted until the training host takes longer rows (the 2026-10-28 stall).
MAX_ROW_CHARS = 2048
MOVE_PAINS = (GamePain.WALL_BUMP, GamePain.WASTED_MOVE)  # grouped by move; room pains by room
MAP_NAME = re.compile(r"\bMAP\d\d\b")
SITUATION = {
    GamePain.WALL_BUMP: "You are about to walk toward a wall.",
    GamePain.WASTED_MOVE: "You are about to repeat a move that may change nothing.",
    GamePain.ROOM_REENTERED: "You are about to leave a room for one you already left.",
    GamePain.ROOM_RECHECKED: "You are about to look around a room you already scanned.",
}


@dataclass(frozen=True)
class FreedoomPaths:
    """The checkout the collector runs in (it holds data/freedoom) and where episodes go."""

    repo: Path
    episodes: Path  # gitignored, e.g. <repo>/data/loop/freedoom
    prereg: Path | None  # frozen prereg for the held-out evaluation; None refuses evaluate


def task_id(level: str, seed: int) -> str:
    """`MAP02/s3`."""
    return f"{level}/s{seed}"


def card_id(lesson: GameLesson) -> str:
    """`freedoom/<pain>/<verb or any>/<check hash>`: one card per transferable habit."""
    verb = lesson.lesson_id.rsplit("/", 1)[-1].split("(")[0] if lesson.pain in MOVE_PAINS else ""
    digest = hashlib.sha256(lesson.check.encode()).hexdigest()[:8]
    return f"freedoom/{lesson.pain.value}/{verb or 'any'}/{digest}"


@dataclass
class Freedoom:
    """The freedoom domain."""

    paths: FreedoomPaths
    runner: CommandRunner
    name: str = "freedoom"
    plain_model: str = PLAIN_GLIMMER
    subject: str = "In Freedoom"
    memory_system: str = REASONING_SYSTEM_MESSAGE
    max_row_chars: int = MAX_ROW_CHARS
    steps: dict[str, list[tuple[str, frozenset[str]]]] = field(default_factory=dict)

    def held_out(self) -> frozenset[str]:
        """MAP04 and MAP08 at seeds 3 and 4."""
        return frozenset(task_id(level, seed) for level in EVAL_LEVELS for seed in EVAL_SEEDS)

    def training_batch(self, round_index: int) -> tuple[str, ...]:
        """Every training level at this round's two new seeds."""
        first = 1 + round_index * SEEDS_PER_ROUND
        seeds = range(first, first + SEEDS_PER_ROUND)
        return tuple(task_id(level, seed) for level in TRAINING_LEVELS for seed in seeds)

    def attempt(
        self, model: str, tasks: Sequence[str], round_index: int, trained: frozenset[str]
    ) -> list[Attempt]:
        """One episode per (level, seed) with the round's model by name."""
        out = self.paths.episodes / f"r{round_index}"
        for task in tasks:
            require_training(task.split("/")[0])
        self._collect(model, tasks, out, None)
        return self._attempts(out, model, tasks, (round_index, Split.TRAINING, trained))

    def evaluate(self, model: str, round_index: int, trained: frozenset[str]) -> list[Attempt]:
        """The held-out episodes; refuses without a frozen prereg."""
        if self.paths.prereg is None:
            raise RuntimeError("held-out Freedoom levels need a frozen prereg (--scored)")
        out = self.paths.episodes / f"eval-r{round_index}"
        tasks = sorted(self.held_out())
        self._collect(model, tasks, out, self.paths.prereg)
        return self._attempts(out, model, tasks, (round_index, Split.HELD_OUT, trained))

    def _collect(self, model: str, tasks: Sequence[str], out: Path, prereg: Path | None) -> None:
        if model.startswith("user-model+"):
            raise RouteNotWiredError("the collector plays Glimmer by name; Route A is not wired")
        by_seed: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            level, seed = task.split("/s")
            by_seed[seed].append(level)
        for seed, levels in sorted(by_seed.items()):
            argv = collect_command(model, levels, int(seed), out / model)
            self.runner.run(argv + (["--scored", str(prereg)] if prereg else []), self.paths.repo)

    def _attempts(
        self, out: Path, model: str, tasks: Sequence[str], context: tuple[int, Split, frozenset]
    ) -> list[Attempt]:
        round_index, split, trained = context
        found = []
        for task in tasks:
            level, seed = task.split("/s")
            path = out / model / level / f"{level}-glimmer_plain-s{seed}.jsonl"
            outcome = episode_outcome(path)
            attempt_id = str(path.relative_to(self.paths.episodes))
            if outcome is not Outcome.UNGRADED:
                self.steps[attempt_id] = episode_steps(path)
            found.append(Attempt(attempt_id, task, round_index, model, split, outcome, trained))
        return found

    def harvest(
        self,
        attempts: Sequence[Attempt],
        known: Mapping[str, LessonCard],
        quotas: Mapping[str, int],
    ) -> Harvest:
        """Game lessons from every graded training episode, pooled into cards by check."""
        dirs = sorted({(self.paths.episodes / a.attempt_id).parent.parent for a in attempts})
        records, situations = [], {}
        for where in dirs:
            found, more = read_history(where)
            records += found
            situations |= more
        lessons = lessons_from_history(records)
        grouped: dict[str, list[GameLesson]] = defaultdict(list)
        for lesson in sorted(lessons.lessons, key=lambda x: -x.repeats):
            require_training(lesson.level)
            grouped[card_id(lesson)].append(lesson)
        first = max((a.round_index for a in attempts), default=0)
        cards = [_card(k, group, known.get(k), first) for k, group in grouped.items()]
        rows = {k: _situation_rows(group, situations) for k, group in grouped.items()}
        return Harvest(tuple(cards), rows, (), sum(lessons.unresolved.values()))

    def mark(self, card: LessonCard, attempt: Attempt) -> Mark:
        """Applies when the episode played the card's verb (any move, for room pains)."""
        steps = self.steps.get(attempt.attempt_id)
        if steps is None:
            steps = episode_steps(self.paths.episodes / attempt.attempt_id)
            self.steps[attempt.attempt_id] = steps
        _, pain, verb, _ = card.lesson_id.split("/")
        relevant = [tags for move, tags in steps if verb in ("any", move)]
        if not relevant:
            return Mark.NOT_APPLICABLE
        return Mark.REPEATED if any(pain in tags for tags in relevant) else Mark.AVOIDED

    def ablate(
        self, model: str, cards: Sequence[LessonCard], attempts: Sequence[Attempt]
    ) -> list[AblationPair]:
        """None: the collector has no lesson-in-prompt path."""
        return []

    def leak_hits(self, texts: Mapping[str, str]) -> dict[str, list[str]]:
        """A text naming a held-out level leaks it."""
        hits = {}
        for key, text in texts.items():
            held = sorted({m for m in MAP_NAME.findall(text) if split_of(m) is LevelSplit.HELD_OUT})
            if held:
                hits[key] = held
        return hits


def _card(
    key: str, group: Sequence[GameLesson], earlier: LessonCard | None, first: int
) -> LessonCard:
    top = group[0]
    sessions = tuple(sorted({lesson.session_id for lesson in group}))
    card = LessonCard(
        key, "freedoom", top.pain.value, SITUATION[top.pain], top.what_happened, top.check,
        sessions, earlier.first_round if earlier else first,
    )  # fmt: skip
    proof = Resolution(ResolutionSource.ENGINE_PROGRESS, sessions)
    return card.resolved_by(proof, top.how_resolved)


def _situation_rows(group: Sequence[GameLesson], situations: Mapping) -> list[Row]:
    """The game prompt at the resolving decision and the moves played there, a few per card."""
    rows = []
    for lesson in group[:SITUATIONS_PER_CHECK]:
        situation: Situation | None = situations.get((lesson.session_id, lesson.resolved_at))
        if situation is not None:
            turns = training_rows(lesson, situation)[-1]["messages"]
            rows.append(Row(card_id(lesson), "situation", tuple(turns)))
    return rows


def collect_command(model: str, levels: Sequence[str], seed: int, out: Path) -> list[str]:
    """The collector line: plain-arm request shape (no lora field), the model by router name."""
    return ["uv", "run", "python", "scripts/act1/collect_episodes.py",
            "--levels", ",".join(levels), "--policies", "glimmer_plain", "--seeds", str(seed),
            "--decisions", str(DECISIONS), "--out", str(out), "--glimmer-model", model]  # fmt: skip


def episode_outcome(path: Path) -> Outcome:
    """PASSED at an exit, FAILED otherwise, UNGRADED when the episode file is missing."""
    if not path.is_file():
        return Outcome.UNGRADED
    with path.open(encoding="utf-8") as handle:
        records = list(load_jsonl(handle))
    ended = json.loads(records[-1].raw)["ended"] if records else None
    return Outcome.PASSED if ended == "exited" else Outcome.FAILED


def episode_steps(path: Path) -> list[tuple[str, frozenset[str]]]:
    """(move verb, pain names) per played move."""
    with path.open(encoding="utf-8") as handle:
        records = list(load_jsonl(handle))
    return [
        (
            (record.command or "").removeprefix("scripted ").split("(")[0],
            frozenset(t.removeprefix("pain:") for t in record.tags if t.startswith("pain:")),
        )
        for record in records
    ]
