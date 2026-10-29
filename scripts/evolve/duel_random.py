"""Random-operator children: the baseline that tells whether reflecting on games beats chance.

For each generation of the selecting arm, children are written by a seeded random operator from
the parent's all-games summary (no best-versus-worst story), play the same cases as the parent
and are scored the way the reflection children are.
"""

import random
import statistics
from dataclasses import dataclass
from typing import Any

import script_paths

script_paths.add_script_dirs()

from collections.abc import Sequence  # noqa: E402

from duel_phases import CHILD_TRIES, ArmSetup, graded_scores, play_pairs  # noqa: E402

from symbiont.act1 import duel  # noqa: E402
from symbiont.act1.card_genome import Card  # noqa: E402
from symbiont.act1.game_fitness import GameResult  # noqa: E402
from symbiont.act1.game_summary import summarize_games  # noqa: E402
from symbiont.act1.generation import call_seed, verdict_on  # noqa: E402
from symbiont.act1.lineage import Birth, Operator  # noqa: E402
from symbiont.act1.run_guards import MutationPromptError  # noqa: E402


@dataclass(frozen=True)
class RandomAsk:
    """One request for a random-operator child: the parent, its all-games summary, where."""

    parent: Card
    summary: str
    generation: int
    slot: int


RANDOM_OPERATORS = (Operator.REWRITE, Operator.ADD, Operator.DELETE, Operator.MERGE)


def random_operator(run_seed: int, generation: int, slot: int = 0) -> Operator:
    """The random operator of a child: seeded, and blind to every game."""
    return random.Random(f"{run_seed}:{generation}:{slot}:random-op").choice(RANDOM_OPERATORS)


def run_random_children(
    parents: dict[int, tuple[Card, Sequence[GameResult], float]], setup: ArmSetup
) -> list[dict[str, Any]]:
    """For each generation, children by random operators from the parent's all-games summary.

    `parents[g]` is the parent card, its games that generation and its mean there. The children
    play the same cases; every row is one child, in the keys one scorer reads for all arms.
    """
    rows = []
    for generation, (parent, games, parent_mean) in sorted(parents.items()):
        pains: dict[str, int] = {}
        for game in games:
            for name, count in game.pains:
                pains[name] = pains.get(name, 0) + count
        summary = summarize_games(games, pains)
        cases = duel.generation_cases(setup.split, generation, setup.run_seed, setup.plan)
        children = _random_children(setup, parent, summary, generation)
        played = play_pairs(
            setup.player, [(child, case) for _, child in children for case in cases]
        )
        for operator, child in children:
            scores = graded_scores(played, child, cases)
            if scores:
                rows.append(
                    {
                        "generation": generation,
                        "arm": "random_operator",
                        "operator": operator.value,
                        "current": parent.card_id,
                        "child": child.card_id,
                        "current_mean": parent_mean,
                        "child_mean": statistics.fmean(scores),
                        "games": len(cases),
                    }
                )
    return rows


def _random_children(
    setup: ArmSetup, parent: Card, summary: str, generation: int
) -> list[tuple[Operator, Card]]:
    """The generation's random-operator children, new and general; the journal keeps them."""
    stored = setup.journal.load(setup.arm, generation)
    if stored is not None:
        return [
            (Operator(birth.operator), card)
            for card, birth in zip(stored[0], stored[1], strict=True)
        ]
    made: list[tuple[Operator, Card]] = []
    for slot in range(setup.plan.children_per_generation):
        ask = RandomAsk(parent, summary, generation, slot)
        made.append(_one_random_child(setup, ask, made))
    author = setup.author.name
    setup.journal.save(
        setup.arm, generation, tuple(card for _, card in made),
        tuple(
            Birth(card.card_id, generation, setup.arm, op, (parent.card_id,), author, None)
            for op, card in made
        ),
    )  # fmt: skip
    return made


def _one_random_child(
    setup: ArmSetup, ask: RandomAsk, made: list[tuple[Operator, Card]]
) -> tuple[Operator, Card]:
    """One child by the slot's random operator; at most CHILD_TRIES asks."""
    operator = random_operator(setup.run_seed, ask.generation, ask.slot)
    for attempt in range(CHILD_TRIES):
        seed = call_seed(setup.run_seed, ask.generation, 100 + ask.slot, attempt)
        child = setup.author.vary(operator, (ask.parent,), ask.summary, seed)
        why = verdict_on(child, (ask.parent,), setup.judge)
        taken = {ask.parent.card_id, *(card.card_id for _, card in made)}
        if why.general and child.card_id not in taken:
            return operator, child
    raise MutationPromptError(f"random operator generation {ask.generation}: no new child")
