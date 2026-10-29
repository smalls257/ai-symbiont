"""A simulated domain for the dry run: no Glimmer, no GPU, deterministic, and labeled as such.

Tasks hide "traps" (the situation a lesson is about). A model that learned a trap's lesson
repeats that mistake less often, except that one lesson is inert and one is misleading (learning
it makes the mistake more likely), so the dry run exercises every utility decision: keep,
probation, down-weight and drop. Nothing here is evidence about Glimmer (a labeled
stand-in); it proves the loop's plumbing, its guards and its accounting.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field

from attempts import Attempt, Outcome, Split, mined_ids
from domain import Harvest
from loop_cards import LessonCard, Resolution, ResolutionSource
from training_plan import SUCCESS_SOURCE, Row
from utility import AblationPair, Mark


@dataclass(frozen=True)
class Trap:
    """One kind of mistake: how often it recurs untaught and once its lesson is learned."""

    name: str
    kind: str
    untaught: float
    taught: float


TRAPS = (
    Trap("edit-once-found", "habit", 0.75, 0.15),
    Trap("one-test-module", "habit", 0.70, 0.25),
    Trap("submit-when-green", "habit", 0.50, 0.10),
    Trap("shared-layer", "repo-knowledge", 0.60, 0.30),
    Trap("test-layout", "repo-knowledge", 0.55, 0.55),  # inert: learning it changes nothing
    Trap("scratch-first", "habit", 0.45, 0.85),  # misleading: learning it makes things worse
)
# Route A stand-in, not measured: the warner speaks at the right moment this often (a trained
# Glimmer carries the lesson every time; a note only arrives when the warner fires).
WARNER_DELIVERY = 0.7
# The shared cross-repo habits base already holds these habit lessons (stand-in for the
# sqlglot-habits adapter and the AIDev habits memory model).
SHARED_HABITS = frozenset({"fake-edit-once-found", "fake-one-test-module"})
SKILL = 0.85  # pass chance of an attempt that falls into no trap
TRAINING_TASKS, HELD_OUT_TASKS, BATCH = 120, 60, 48
ABLATION_SAMPLE = 4  # applicable tasks per lesson in use, run with and without its card
SYSTEM = "You are Glimmer, working on simulated tasks. Answer in plain prose.\n\nReasoning: low."


def _chance(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def lesson_id_of(trap: Trap) -> str:
    """The card id a trap's lesson gets."""
    return f"fake-{trap.name}"


def traps_of(task: str) -> tuple[Trap, ...]:
    """One or two traps per task, fixed by the task id."""
    first = TRAPS[int(_chance(task, "a") * len(TRAPS))]
    second = TRAPS[int(_chance(task, "b") * len(TRAPS))]
    return (first,) if _chance(task, "two") < 0.5 or second == first else (first, second)


@dataclass
class FakeDomain:
    """The simulated domain; `learned` is shared with FakeTrainer (model name -> lesson ids)."""

    learned: MutableMapping[str, frozenset[str]] = field(default_factory=dict)
    name: str = "fake"
    plain_model: str = "fake-plain"
    subject: str = "In the simulated repo"
    memory_system: str = SYSTEM
    max_row_chars: int = 2048
    delivery: float = 1.0  # chance a learned lesson reaches the moment it is needed
    repeated: dict[str, frozenset[str]] = field(default_factory=dict)  # attempt -> trap names

    def held_out(self) -> frozenset[str]:
        """Held-out ids are h-prefixed and never in a training batch."""
        return frozenset(f"h{i:03d}" for i in range(HELD_OUT_TASKS))

    def training_batch(self, round_index: int) -> tuple[str, ...]:
        """A window of BATCH training tasks that moves each round."""
        start = round_index * BATCH
        return tuple(f"t{(start + i) % TRAINING_TASKS:03d}" for i in range(BATCH))

    def _play(self, task: str, tag: str, lessons: frozenset[str]) -> tuple[bool, set]:
        """Common random numbers: every arm sees the same draws, so gaps come from lessons."""
        hits = set()
        for trap in traps_of(task):
            delivered = _chance(task, tag, trap.name, "note") < self.delivery
            known = lesson_id_of(trap) in lessons and delivered
            recur = trap.taught if known else trap.untaught
            if _chance(task, tag, trap.name) < recur:
                hits.add(trap.name)
        return not hits and _chance(task, tag, "skill") < SKILL, hits

    def _run(self, model: str, tasks: Sequence[str], round_index: int, split: Split) -> list:
        lessons = self.learned.get(model, frozenset())
        found = []
        for task in tasks:
            attempt_id = f"r{round_index}/{split}/{model}/{task}"
            passed, hits = self._play(
                task, f"r{round_index}" if split is Split.TRAINING else "eval", lessons
            )
            self.repeated[attempt_id] = frozenset(hits)
            outcome = Outcome.PASSED if passed else Outcome.FAILED
            found.append(Attempt(attempt_id, task, round_index, model, split, outcome, lessons))
        return found

    def attempt(
        self, model: str, tasks: Sequence[str], round_index: int, trained: frozenset[str]
    ) -> list[Attempt]:
        """Simulated graded attempts on training tasks."""
        return self._run(model, tasks, round_index, Split.TRAINING)

    def evaluate(self, model: str, round_index: int, trained: frozenset[str]) -> list[Attempt]:
        """Simulated graded attempts on every held-out task."""
        return self._run(model, sorted(self.held_out()), round_index, Split.HELD_OUT)

    def mark(self, card: LessonCard, attempt: Attempt) -> Mark:
        """Applies when the task holds the card's trap; repeated when the attempt fell into it."""
        trap = card.lesson_id.removeprefix("fake-")
        if trap not in {t.name for t in traps_of(attempt.task_id)}:
            return Mark.NOT_APPLICABLE
        return Mark.REPEATED if trap in self.repeated[attempt.attempt_id] else Mark.AVOIDED

    def harvest(
        self,
        attempts: Sequence[Attempt],
        known: Mapping[str, LessonCard],
        quotas: Mapping[str, int],
    ) -> Harvest:
        """A card per trap someone fell into; closed once a passed attempt got past that trap."""
        mined_ids(attempts)
        cards = [card for trap in TRAPS if (card := self._card(trap, attempts, known))]
        passed = [a for a in attempts if a.passed][:20]
        success = tuple(
            Row(f"{SUCCESS_SOURCE}:{a.attempt_id}", "success", _success_turns(a.task_id))
            for a in passed
        )
        open_traps = sum(card.is_open for card in cards)
        return Harvest(tuple(cards), {}, success, open_traps)

    def _card(
        self, trap: Trap, attempts: Sequence[Attempt], known: Mapping[str, LessonCard]
    ) -> LessonCard | None:
        fell = [a for a in attempts if trap.name in self.repeated.get(a.attempt_id, ())]
        if not fell:
            return None
        got_past = [
            a.attempt_id
            for a in attempts
            if a.passed and trap.name in {t.name for t in traps_of(a.task_id)}
        ]
        earlier = known.get(lesson_id_of(trap))
        card = LessonCard(
            lesson_id=lesson_id_of(trap),
            domain=self.name,
            kind=trap.kind,
            situation=f"You are at the point where {trap.name.replace('-', ' ')} matters.",
            what_happened=f"The run fell into {trap.name.replace('-', ' ')}.",
            check=f"Before the next step, check for {trap.name.replace('-', ' ')}.",
            source_tasks=tuple(sorted({a.task_id for a in fell}))[:10],
            first_round=earlier.first_round if earlier else max(a.round_index for a in attempts),
        )
        if not got_past:
            return card
        proof = Resolution(ResolutionSource.OWN_VERIFIED_SUCCESS, tuple(got_past[:5]))
        return card.resolved_by(proof, f"A passing run avoided {trap.name.replace('-', ' ')}.")

    def ablate(
        self, model: str, cards: Sequence[LessonCard], attempts: Sequence[Attempt]
    ) -> list[AblationPair]:
        """With and without the card, on ABLATION_SAMPLE applicable tasks per lesson held."""
        held = self.learned.get(model, frozenset())
        pairs = []
        for card in (c for c in cards if c.lesson_id in held):
            sample = [a for a in attempts if self.mark(card, a) is not Mark.NOT_APPLICABLE]
            for attempt in sample[:ABLATION_SAMPLE]:
                with_card, _ = self._play(attempt.task_id, "abl", held)
                without, _ = self._play(attempt.task_id, "abl", held - {card.lesson_id})
                pairs.append(AblationPair(card.lesson_id, attempt.task_id, with_card, without))
        return pairs

    def leak_hits(self, texts: Mapping[str, str]) -> dict[str, list[str]]:
        """A text naming a held-out task id leaks it."""
        held = self.held_out()
        return {
            k: sorted(h for h in held if h in t)
            for k, t in texts.items()
            if any(h in t for h in held)
        }


def _success_turns(task: str) -> tuple[dict[str, str], ...]:
    return (
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Simulated task {task}: what is your next action?"},
        {"role": "assistant", "content": "Edit the file that holds the fault, then run its test."},
    )
