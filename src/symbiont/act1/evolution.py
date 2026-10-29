"""The whole loop over a Player: generation 0, noise check, generations, gap watch, picks (pure).

Nothing here touches an engine or a model. A dry run drives it with a fake player; a real run
drives it with the engine player in scripts/evolve. Held-out levels never reach the player:
`evolve` plays selection and validation cases only, and the final test is a separate run.
"""

import copy
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from symbiont.act1.card_archive import Archive
from symbiont.act1.card_genome import Card
from symbiont.act1.card_picking import GameRole, PlayedGame, pick_best
from symbiont.act1.evolve_split import EvolveSplit, generation_cases, validation_cases
from symbiont.act1.game_fitness import Case, GameResult, Grade, fitness
from symbiont.act1.game_summary import summarize_games
from symbiont.act1.generation import ParentChoice, Population, VariationTools, next_population
from symbiont.act1.lexicase import FitnessTable
from symbiont.act1.lineage import Arm, Birth
from symbiont.act1.run_guards import (
    GapDecision,
    GapWatch,
    NoiseReport,
    NoiseVerdict,
    SpendRoom,
    noise_check,
    require_graded_share,
)

CHOICE = {Arm.EVOLVED: ParentChoice.LEXICASE, Arm.NO_SELECTION: ParentChoice.RANDOM}
NOISE_CARDS = 3  # design section 5.6: three cards replay the generation-0 levels with a second seed
LEVELS_PER_BLOCK = 4  # one block is one seed on each of a generation's four levels


class Player(Protocol):
    """Plays one card on one case. Returns an ungraded result for a model error, never a guess."""

    def play(self, card: Card, case: Case) -> GameResult:
        """One game."""
        ...


class UnexpectedLevelError(ValueError):
    """A case on a level that is neither a selection nor a validation level."""


@dataclass(frozen=True)
class RunRules:
    """What a run is told before it starts."""

    generations: int
    run_seed: int
    games_per_case: int
    spend_room: SpendRoom


@dataclass
class RunRecord:
    """Everything a run produced, for the report and the progress page."""

    noise: NoiseReport | None = None
    games_per_case: int = 1
    tables: dict[Arm, list[FitnessTable]] = field(default_factory=dict)
    gaps: list[tuple[int, float, float]] = field(default_factory=list)
    births: list[Birth] = field(default_factory=list)
    archives: dict[Arm, Archive] = field(default_factory=dict)
    picks: dict[Arm, str] = field(default_factory=dict)
    games: list[PlayedGame] = field(default_factory=list)
    validation_games: list[PlayedGame] = field(default_factory=list)
    cards: dict[str, Card] = field(default_factory=dict)
    stop_reason: str | None = None
    last_played: int = 0
    last_good: int = 0


@dataclass
class _ArmState:
    """One arm's current population, its latest games and every card id it ever held."""

    population: Population
    results: list[GameResult]
    card_ids: set[str] = field(default_factory=set)


def _mean(results: Sequence[GameResult]) -> float:
    """Mean fitness of the graded games."""
    return statistics.fmean(fitness(r) for r in results if r.grade == Grade.GRADED)


def _summaries(results: Sequence[GameResult], cards: Sequence[Card]) -> dict[str, str]:
    """A prose summary per card from its games and tagger counts."""
    out = {}
    for card in cards:
        mine = [r for r in results if r.card_id == card.card_id]
        pains: dict[str, int] = {}
        for result in mine:
            for name, count in result.pains:
                pains[name] = pains.get(name, 0) + count
        out[card.card_id] = summarize_games(mine, pains)
    return out


class _Run:
    """State of one evolve call; each method is one named step of the loop."""

    def __init__(self, split: EvolveSplit, player: Player, rules: RunRules) -> None:
        """Start an empty record."""
        self.split, self.player, self.rules = split, player, rules
        self.record = RunRecord(games_per_case=rules.games_per_case)
        self.cards = self.record.cards
        self._played: dict[tuple[str, Case], GameResult] = {}

    def play(
        self, cards: Sequence[Card], cases: Sequence[Case], generation: int, role: GameRole
    ) -> list[GameResult]:
        """Every card on every case. A pair already played this run is not played again."""
        results = []
        for card in cards:
            self.cards[card.card_id] = card
            results.extend(self._game(card, case, generation, role) for case in cases)
        return results

    def _game(self, card: Card, case: Case, generation: int, role: GameRole) -> GameResult:
        """One game through the level guard, logged once."""
        key = (card.card_id, case)
        if key in self._played:
            return self._played[key]
        if role == GameRole.VALIDATION and case.level not in self.split.validation:
            raise UnexpectedLevelError(f"{case.level} is not a validation level")
        if role == GameRole.SELECTION:
            self.split.require_selection(case.level)
        result = self.player.play(card, case)
        self._played[key] = result
        log = self.record.validation_games if role == GameRole.VALIDATION else self.record.games
        log.append(PlayedGame(result, generation, role))
        return result

    def generation_zero(self, seeds: Sequence[Card]) -> tuple[list[GameResult], NoiseReport] | None:
        """Play the seed cards, run the noise check, double the games if told; None on STOP."""
        rules = self.rules
        blocks = generation_cases(self.split, 0, rules.run_seed, 2)
        first, second = blocks[:LEVELS_PER_BLOCK], blocks[LEVELS_PER_BLOCK:]
        results = self.play(seeds, first, 0, GameRole.SELECTION)
        require_graded_share(results)
        noisy = list(seeds[:NOISE_CARDS])
        self.play(noisy, second, 0, GameRole.SELECTION)
        noise = noise_check(self._replays(noisy, first, second), rules.spend_room)
        self.record.noise = noise
        if noise.verdict == NoiseVerdict.STOP:
            self.record.stop_reason = (
                "noise: seed noise exceeds card differences, doubling does not fit"
            )
            return None
        if noise.verdict == NoiseVerdict.DOUBLE_GAMES:
            self.record.games_per_case = rules.games_per_case * 2
        every = generation_cases(self.split, 0, rules.run_seed, self.record.games_per_case)
        return self.play(seeds, every, 0, GameRole.SELECTION), noise

    def _replays(
        self, cards: Sequence[Card], first: Sequence[Case], second: Sequence[Case]
    ) -> dict[str, tuple[tuple[float, float], ...]]:
        """Seed pairs per card and level, leaving out a level where any noise game is ungraded."""

        def result(card: Card, case: Case) -> GameResult:
            return self._played[(card.card_id, case)]

        def graded(level: int) -> bool:
            games = [result(c, case) for c in cards for case in (first[level], second[level])]
            return all(game.grade == Grade.GRADED for game in games)

        whole_levels = [i for i in range(LEVELS_PER_BLOCK) if graded(i)]
        return {
            card.card_id: tuple(
                (fitness(result(card, first[i])), fitness(result(card, second[i])))
                for i in whole_levels
            )
            for card in cards
        }

    def advance(
        self, generation: int, arms: Mapping[Arm, _ArmState], tools: VariationTools
    ) -> None:
        """Both arms vary their cards, then play the generation's shared cases."""
        cases = generation_cases(
            self.split, generation, self.rules.run_seed, self.record.games_per_case
        )
        for arm, state in arms.items():
            own = replace(
                copy.deepcopy(tools),
                rng=random.Random(f"{self.rules.run_seed}:{arm}"),
                summaries=_summaries(state.results, state.population.cards),
            )
            step = next_population(state.population, state.results, CHOICE[arm], own)
            self.record.births.extend(step.births)
            for card, mean in step.archive_offers:
                self.record.archives.setdefault(arm, Archive()).offer(card, mean)
            state.population = step.population
            state.card_ids.update(card.card_id for card in step.population.cards)
            state.results = self.play(step.population.cards, cases, generation, GameRole.SELECTION)
            require_graded_share(state.results)
            self.record.tables.setdefault(arm, []).append(FitnessTable.of(state.results))
        self.record.last_played = generation

    def validate(self, generation: int, state: _ArmState) -> None:
        """The evolved arm's best card of this generation plays the validation levels."""
        table = self.record.tables[Arm.EVOLVED][-1]
        best = max(
            state.population.cards, key=lambda card: (_mean_card(table, card), -card.words())
        )
        training = _mean([r for r in state.results if r.card_id == best.card_id])
        cases = validation_cases(self.split, generation, self.rules.run_seed)
        results = self.play([best], cases, generation, GameRole.VALIDATION)
        require_graded_share(results)
        self.record.gaps.append((generation, training, _mean(results)))

    def pick(self, arms: Mapping[Arm, _ArmState]) -> None:
        """Each arm's pick over the last two good generations, by the one shared rule."""
        last = self.record.last_good
        for arm, state in arms.items():
            mine = [g for g in self.record.games if g.result.card_id in state.card_ids]
            self.record.picks[arm] = pick_best(
                mine, (max(last - 1, 0), last), lambda cid: self.cards[cid].tie_key()
            )


def _mean_card(table: FitnessTable, card: Card) -> float:
    """A card's mean fitness over the table's kept cases (0 if the card is not in the table)."""
    scores = [
        table.scores[(card.card_id, case)]
        for case in table.cases
        if (card.card_id, case) in table.scores
    ]
    return statistics.fmean(scores) if scores else float("-inf")


def evolve(
    seed_population: Sequence[Card],
    split: EvolveSplit,
    player: Player,
    tools: VariationTools,
    rules: RunRules,
) -> RunRecord:
    """Generation 0, the noise check, then generations 1 to N for both arms, gap watch, picks.

    Raises TooManyUngradedError in the generation where more than 10% of games ended ungraded.
    """
    run = _Run(split, player, rules)
    zero = run.generation_zero(seed_population)
    if zero is None:
        return run.record
    results, noise = zero
    first_table = FitnessTable.of(results)
    run.record.tables = {arm: [first_table] for arm in CHOICE}
    arms = {
        arm: _ArmState(
            Population(0, arm, tuple(seed_population)),
            results,
            {c.card_id for c in seed_population},
        )
        for arm in CHOICE
    }
    watch = GapWatch(noise.standard_error)
    for generation in range(1, rules.generations + 1):
        run.advance(generation, arms, tools)
        run.validate(generation, arms[Arm.EVOLVED])
        watch.record(generation, *run.record.gaps[-1][1:])
        verdict = watch.verdict()
        if verdict.decision == GapDecision.STOP:
            run.record.stop_reason = f"gap: {verdict.detail}"
            run.record.last_good = verdict.last_good_generation or 0
            break
        run.record.last_good = generation
    if rules.generations > 0:
        run.pick(arms)
    return run.record
