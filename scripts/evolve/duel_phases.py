"""The three phases of Evolve run 2, over a Player and an Author so they can be tested offline.

Noise: one card replayed on the same cases. Evolve: each arm, every generation, plays its current
best card and one child on the same fresh cases; the child is written from the best and worst
games of the current best; the selecting arm keeps the better card, the control a coin's pick.
Final: three cards on the same fresh cases, half on held-back maps.
"""

import logging
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1 import duel  # noqa: E402 - needs the sibling path added above
from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.evolution import Journal, Player  # noqa: E402
from symbiont.act1.evolve_split import EvolveSplit  # noqa: E402
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness  # noqa: E402
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
class ChildAsk:
    """One request for a child: whose child, what it reads, which generation and slot."""

    parent: Card
    text: str
    generation: int
    slot: int


@dataclass(frozen=True)
class GenerationPlay:
    """What one generation's games gave: the cards, their scores, who stayed, how many cases."""

    number: int
    current: Card
    children: list[Card]
    scores: dict[str, list[float]]
    survivor: Card
    cases: int


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
    plan: duel.DuelPlan = duel.RUN2


class ArmRunner:
    """The plan's generations for one arm; fresh cases every round, nothing carried over."""

    def __init__(self, setup: ArmSetup) -> None:
        """Hold the setup and an empty record."""
        self.setup, self.run = setup, ArmRun(setup.arm)

    def children_of(
        self, current: Card, games: Sequence[GameResult], generation: int
    ) -> list[Card]:
        """The generation's new general children of `current` from its best and worst games."""
        setup = self.setup
        stored = setup.journal.load(setup.arm, generation)
        if stored is not None:
            self.run.births.extend(stored[1])
            return list(stored[0])
        text = duel.compare_text(games)
        children: list[Card] = []
        births: list[Birth] = []
        for slot in range(setup.plan.children_per_generation):
            ask = ChildAsk(current, text, generation, slot)
            child = self._ask(ask, [current, *children], births)
            children.append(child)
        setup.journal.save(setup.arm, generation, tuple(children), tuple(births))
        self.run.births.extend(births)
        return children

    def _ask(self, ask: ChildAsk, taken: list[Card], births: list[Birth]) -> Card:
        """One new general child, different from the parent and the earlier children."""
        setup = self.setup
        for attempt in range(CHILD_TRIES):
            seed = call_seed(setup.run_seed, ask.generation, ask.slot, attempt)
            child = setup.author.vary(Operator.COMPARE, (ask.parent,), ask.text, seed)
            why = verdict_on(child, (ask.parent,), setup.judge)
            births.append(self._birth(child, ask.parent, ask.generation, why.rejection))
            if why.general and all(child.card_id != card.card_id for card in taken):
                return child
            reason = why.rejection.value if why.rejection else "same card as an earlier one"
            log.warning(
                "%s generation %d child %d ask %d turned away: %s",
                setup.arm.value, ask.generation, ask.slot + 1, attempt + 1, reason,
            )  # fmt: skip
        raise MutationPromptError(f"{setup.arm.value} generation {ask.generation}: no new child")

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
        """Play current and its children on this generation's cases; return the survivor."""
        setup = self.setup
        children = self.children_of(current, traces, number)
        cases = duel.generation_cases(setup.split, number, setup.run_seed, setup.plan)
        cards = [current, *children]
        played = play_pairs(setup.player, [(card, case) for card in cards for case in cases])
        scores = {card.card_id: graded_scores(played, card, cases) for card in cards}
        candidates = [(card, scores[card.card_id]) for card in cards if scores[card.card_id]]
        coin = random.Random(f"{setup.run_seed}:{number}:coin")
        survivor = duel.pick_among(candidates, CHOICE[setup.arm], coin)
        play = GenerationPlay(number, current, children, scores, survivor, len(cases))
        self.run.rows.append(self._row(play))
        return survivor, [played[(survivor.card_id, case)] for case in cases]

    def _row(self, play: GenerationPlay) -> dict[str, Any]:
        """One generation's numbers; `child` and `child_mean` are the first child's, as in run 2."""
        means = {cid: statistics.fmean(v) for cid, v in play.scores.items() if v}
        first = play.children[0].card_id
        return {
            "generation": play.number,
            "arm": self.setup.arm.value,
            "current": play.current.card_id,
            "child": first,
            "current_mean": means[play.current.card_id],
            "child_mean": means.get(first),
            "children": [
                {"id": child.card_id, "mean": means[child.card_id]}
                for child in play.children
                if child.card_id in means
            ],
            "kept": play.survivor.card_id,
            "games": (1 + len(play.children)) * play.cases,
        }

    def go(self, start: Card, start_games: Sequence[GameResult]) -> ArmRun:
        """All generations from the start card and the games its first children are written from."""
        current, traces = start, list(start_games)
        for number in range(1, self.setup.plan.generations + 1):
            current, traces = self.generation(current, traces, number)
        self.run.final = current
        return self.run


def reflection_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, float]]:
    """One row per child (current_mean, child_mean), whether a generation had one child or many."""
    flat = []
    for row in rows:
        children = row.get("children") or [{"mean": row["child_mean"]}]
        flat += [
            {"current_mean": row["current_mean"], "child_mean": child["mean"]} for child in children
        ]
    return flat


def run_final(
    cards: dict[str, Card],
    selection: Sequence[Case],
    held_back: Sequence[Case],
    players: Mapping[str, Player],
) -> dict[str, dict[Case, float]]:
    """Every card on every case, each name with its own player and so its own games.

    Two names holding the same card (the control ended where it began) are two independent
    replays, not one cached game. Fitness by name and case; ungraded games are left out.
    """
    cases = [*selection, *held_back]
    scores: dict[str, dict[Case, float]] = {}
    for name, card in cards.items():
        played = play_pairs(players[name], [(card, case) for case in cases])
        graded = {case: played[(card.card_id, case)] for case in cases}
        scores[name] = {c: fitness(g) for c, g in graded.items() if g.grade == Grade.GRADED}
    return scores


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
        "evolved arm": duel.child_share(reflection_rows(arms["evolved"]["rows"])),
        "no-selection arm": duel.child_share(reflection_rows(arms["control"]["rows"])),
    }
    if "random" in arms:
        shares["random operator"] = duel.child_share(reflection_rows(arms["random"]["rows"]))
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
