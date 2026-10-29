"""The three phases of Evolve run 2, over a Player and an Author so they can be tested offline.

Noise: one card replayed on the same cases. Evolve: each arm, every generation, plays its current
best card and one child on the same fresh cases; the child is written from the best and worst
games of the current best; the selecting arm keeps the better card, the control a coin's pick.
Final: three cards on the same fresh cases, half on held-back maps.
"""

import logging
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1 import duel  # noqa: E402 - needs the sibling path added above
from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolution import Journal, Player  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
from symbiont.act1.game_summary import summarize_games  # noqa: E402
from symbiont.act1.generation import Author, Judge, ParentChoice, call_seed, verdict_on  # noqa: E402
from symbiont.act1.lineage import Arm, Birth, Operator  # noqa: E402
from symbiont.act1.run_guards import MutationPromptError  # noqa: E402

log = logging.getLogger(__name__)
CHILD_TRIES = 3
CHOICE = {Arm.EVOLVED: ParentChoice.LEXICASE, Arm.NO_SELECTION: ParentChoice.RANDOM}


def play_pairs(
    player: Player, pairs: Sequence[tuple[Card, Case]]
) -> dict[tuple[str, Case], GameResult]:
    """Play the pairs (as one parallel batch if the player can); results by (card id, case)."""
    found: dict[tuple[str, Case], GameResult] = {}

    def keep(card: Card, case: Case, result: GameResult) -> None:
        found[(card.card_id, case)] = result

    many = getattr(player, "play_many", None)
    if many is not None:
        many(list(pairs), keep)
    else:
        for card, case in pairs:
            keep(card, case, player.play(card, case))
    return found


def run_noise(card: Card, cases: Sequence[Case], players: Sequence[Player]) -> dict[str, Any]:
    """The same card on the same cases once per player (one player per replicate)."""
    replicates = []
    for player in players:
        played = play_pairs(player, [(card, case) for case in cases])
        replicates.append([fitness(played[(card.card_id, case)]) for case in cases])
    return duel.replay_noise(replicates) | {"games": len(players) * len(cases)}


@dataclass
class ArmRun:
    """What one arm did: a row per generation and the card it ends with."""

    arm: Arm
    rows: list[dict[str, Any]] = field(default_factory=list)
    final: Card | None = None
    births: list[Birth] = field(default_factory=list)


def graded_scores(
    played: dict[tuple[str, Case], GameResult], card: Card, cases: Sequence[Case]
) -> list[float]:
    """The card's fitness on the cases whose games were graded."""
    games = [played[(card.card_id, case)] for case in cases]
    return [fitness(game) for game in games if game.grade == Grade.GRADED]


@dataclass(frozen=True)
class ArmSetup:
    """Everything one arm needs; the two arms differ only in `arm` (and so in how they keep)."""

    arm: Arm
    split: EvolveSplit
    run_seed: int
    player: Player
    author: Author
    judge: Judge
    journal: Journal


class ArmRunner:
    """GENERATIONS rounds for one arm; fresh cases every round, nothing carried over."""

    def __init__(self, setup: ArmSetup) -> None:
        """Hold the setup and an empty record."""
        self.setup, self.run = setup, ArmRun(setup.arm)

    def child_of(self, current: Card, games: Sequence[GameResult], generation: int) -> Card:
        """A new general child of `current` from its best and worst games, or the stored one."""
        setup = self.setup
        stored = setup.journal.load(setup.arm, generation)
        if stored is not None:
            self.run.births.extend(stored[1])
            return stored[0][0]
        text = duel.compare_text(games)
        births: list[Birth] = []
        for attempt in range(CHILD_TRIES):
            seed = call_seed(setup.run_seed, generation, 0, attempt)
            child = setup.author.vary(Operator.COMPARE, (current,), text, seed)
            why = verdict_on(child, (current,), setup.judge)
            births.append(self._birth(child, current, generation, why.rejection))
            if not (why.general and child.card_id != current.card_id):
                reason = why.rejection.value if why.rejection else "same card as the parent"
                log.warning(
                    "%s generation %d ask %d turned away: %s",
                    setup.arm.value,
                    generation,
                    attempt + 1,
                    reason,
                )
            if why.general and child.card_id != current.card_id:
                setup.journal.save(setup.arm, generation, (child,), tuple(births))
                self.run.births.extend(births)
                return child
        raise MutationPromptError(f"{setup.arm.value} generation {generation}: no new child")

    def _birth(self, child: Card, current: Card, generation: int, rejection: Any) -> Birth:
        """The child's birth record."""
        author = self.setup.author.name
        return Birth(
            child.card_id, generation, self.setup.arm, Operator.COMPARE,
            (current.card_id,), author, rejection,
        )  # fmt: skip

    def generation(
        self, current: Card, traces: Sequence[GameResult], number: int
    ) -> tuple[Card, list[GameResult]]:
        """Play current and child on this generation's cases; return the survivor and its games."""
        setup = self.setup
        child = self.child_of(current, traces, number)
        cases = duel.generation_cases(setup.split, number, setup.run_seed)
        pairs = [(card, case) for card in (current, child) for case in cases]
        played = play_pairs(setup.player, pairs)
        scores = {card.card_id: graded_scores(played, card, cases) for card in (current, child)}
        coin = random.Random(f"{setup.run_seed}:{number}:coin")
        pair = ((current, scores[current.card_id]), (child, scores[child.card_id]))
        survivor = duel.pick_survivor(*pair, CHOICE[setup.arm], coin)
        self.run.rows.append(self._row(number, pair, survivor, len(cases)))
        return survivor, [played[(survivor.card_id, k)] for k in cases]

    def _row(self, number: int, pair: Any, survivor: Card, cases: int) -> dict[str, Any]:
        """One generation's numbers: both cards' means on this generation's cases and who stayed."""
        (current, current_scores), (child, child_scores) = pair
        return {
            "generation": number,
            "arm": self.setup.arm.value,
            "current": current.card_id,
            "child": child.card_id,
            "current_mean": statistics.fmean(current_scores),
            "child_mean": statistics.fmean(child_scores),
            "kept": survivor.card_id,
            "games": 2 * cases,
        }

    def go(self, start: Card, start_games: Sequence[GameResult]) -> ArmRun:
        """All generations from the start card and the games its first child is written from."""
        current, traces = start, list(start_games)
        for number in range(1, duel.GENERATIONS + 1):
            current, traces = self.generation(current, traces, number)
        self.run.final = current
        return self.run


RANDOM_OPERATORS = (Operator.REWRITE, Operator.ADD, Operator.DELETE, Operator.MERGE)


def random_operator(run_seed: int, generation: int) -> Operator:
    """The random operator of a generation: seeded, and blind to every game."""
    return random.Random(f"{run_seed}:{generation}:random-op").choice(RANDOM_OPERATORS)


def run_random_children(
    parents: dict[int, tuple[Card, Sequence[GameResult], float]], setup: ArmSetup
) -> list[dict[str, Any]]:
    """For each generation, a child by a random operator from the parent's all-games summary.

    `parents[g]` is the parent card, its games that generation and its mean there. The child plays
    the same cases; the row shares the keys of an arm's rows so one scorer reads both.
    """
    rows = []
    for generation, (parent, games, parent_mean) in sorted(parents.items()):
        operator = random_operator(setup.run_seed, generation)
        pains: dict[str, int] = {}
        for game in games:
            for name, count in game.pains:
                pains[name] = pains.get(name, 0) + count
        summary = summarize_games(games, pains)
        child = _random_child(setup, operator, parent, summary, generation)
        cases = duel.generation_cases(setup.split, generation, setup.run_seed)
        played = play_pairs(setup.player, [(child, case) for case in cases])
        rows.append(
            {
                "generation": generation,
                "arm": "random_operator",
                "operator": operator.value,
                "current": parent.card_id,
                "child": child.card_id,
                "current_mean": parent_mean,
                "child_mean": statistics.fmean(graded_scores(played, child, cases)),
                "games": len(cases),
            }
        )
    return rows


def _random_child(
    setup: ArmSetup, operator: Operator, parent: Card, summary: str, generation: int
) -> Card:
    """A new general child by the operator; at most CHILD_TRIES asks (the journal keeps it)."""
    stored = setup.journal.load(setup.arm, generation)
    if stored is not None:
        return stored[0][0]
    for attempt in range(CHILD_TRIES):
        seed = call_seed(setup.run_seed, generation, 1, attempt)
        child = setup.author.vary(operator, (parent,), summary, seed)
        why = verdict_on(child, (parent,), setup.judge)
        if why.general and child.card_id != parent.card_id:
            birth = Birth(
                child.card_id, generation, setup.arm, operator, (parent.card_id,),
                setup.author.name, None,
            )  # fmt: skip
            setup.journal.save(setup.arm, generation, (child,), (birth,))
            return child
    raise MutationPromptError(f"random operator generation {generation}: no new child")


def run_final(
    cards: dict[str, Card], selection: Sequence[Case], held_back: Sequence[Case], player: Player
) -> dict[str, dict[Case, float]]:
    """Every card on every case; fitness by card name and case (ungraded games are left out)."""
    cases = [*selection, *held_back]
    played = play_pairs(player, [(card, case) for card in cards.values() for case in cases])
    return {
        name: {
            case: fitness(played[(card.card_id, case)])
            for case in cases
            if played[(card.card_id, case)].grade == Grade.GRADED
        }
        for name, card in cards.items()
    }


def paired_table(
    scores: dict[str, dict[Case, float]], held_back: Sequence[Case], draw_seed: int
) -> list[dict[str, Any]]:
    """Three pairings of the three cards, each over all cases, selection maps and held-back maps."""
    held = set(held_back)
    parts: dict[str, Callable[[Case], bool]] = {
        "all": lambda case: True,
        "selection maps": lambda case: case not in held,
        "held-back maps": lambda case: case in held,
    }
    rows = []
    for first, second in (("evolved", "control"), ("evolved", "gen0"), ("control", "gen0")):
        for part, wanted in parts.items():
            kept = {
                name: {c: v for c, v in scores[name].items() if wanted(c)}
                for name in (first, second)
            }
            groups = duel.paired_groups(kept, first, second)
            diffs = [d for values in groups.values() for d in values]
            low, high = duel.paired_interval(groups, draw_seed)
            rows.append(
                {
                    "label": f"{first} minus {second}, {part}",
                    "role": "under_test" if first == "evolved" else "reference",
                    "pairs": len(diffs),
                    "mean_difference": statistics.fmean(diffs),
                    "low": low,
                    "high": high,
                    "word": duel.decision_word(low, high),
                }
            )
    return rows


def _generation_rows(arms: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One labeled row per arm and generation: both cards' means and whether the child stayed."""
    rows = []
    for arm_name, arm in arms.items():
        role = "under_test" if arm_name == "evolved" else "reference"
        for row in arm["rows"]:
            kept = {"child_kept": row["kept"] == row["child"]} if "kept" in row else {}
            rows.append(
                {
                    "label": f"{arm_name} generation {row['generation']}",
                    "role": role,
                    "current_mean": row["current_mean"],
                    "child_mean": row["child_mean"],
                    **kept,
                }
            )
    return rows


def _reflection(arms: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    """The share of children that beat their parent, per way of writing children."""
    shares = {
        "evolved arm": duel.child_share(arms["evolved"]["rows"]),
        "no-selection arm": duel.child_share(arms["control"]["rows"]),
    }
    if "random" in arms:
        shares["random operator"] = duel.child_share(arms["random"]["rows"])
    return shares


def build_report(
    noise: dict[str, Any],
    arms: dict[str, dict[str, Any]],
    final: dict[str, Any],
    spend: dict[str, Any],
) -> dict[str, Any]:
    """The run's report: noise and its half-width, both arms' rows, the paired table, the spend."""
    cases = sum(final["games"].values()) // len(final["games"])
    half_width = duel.expected_half_width(noise["replay_variance"], cases)
    roles = {"gen0": "reference", "control": "reference", "evolved": "under_test"}
    cards = [
        {"label": f"{name} card, final test", "role": roles[name], "mean_fitness": mean}
        for name, mean in final["means"].items()
    ]
    return {
        "schema": "evolve-run2-v1",
        "label": "exploratory run 2, Spark low reasoning, temperature 0 [measured]",
        "claim": "exploratory",
        "noise": noise
        | {"expected_half_width_of_a_paired_difference": half_width, "paired_cases": cases},
        "reflection": _reflection(arms),
        "final_ids": final["ids"],
        "paired": final["table"],
        "rows": cards + _generation_rows(arms),
        "spend": spend,
    }
