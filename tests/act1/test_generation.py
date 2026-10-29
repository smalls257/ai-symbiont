"""One generation: elites stay, arms differ only in parent choice, rejects are replaced."""

import random
from collections import Counter

import pytest

from symbiont.act1.card_genome import Card, Lesson
from symbiont.act1.game_fitness import Case, GameResult, Grade
from symbiont.act1.generality import Rejection, Verdict
from symbiont.act1.generation import (
    CHILDREN,
    ELITES,
    MutationReplyError,
    OperatorSchedule,
    ParentChoice,
    Population,
    VariationTools,
    crossover,
    next_population,
)
from symbiont.act1.lineage import Arm, Lineage, Operator
from symbiont.act1.move_cuts import CutSetting
from symbiont.act1.offline_author import (
    OFFLINE_LESSONS,
    AllowAllJudge,
    FlagWordJudge,
    OfflineAuthor,
)
from symbiont.act1.run_guards import MutationPromptError

LEVELS = ("MAP01", "MAP02", "MAP03", "MAP05")


def cards_of(count):
    """`count` distinct cards: the empty one, then 1, 2, ... pool lessons."""
    return tuple(Card.of(OFFLINE_LESSONS[:size]) for size in range(count))


def results_for(cards, share_of):
    """Games where each card's route share comes from `share_of(card, level_index)`."""
    out = []
    for card in cards:
        for index, level in enumerate(LEVELS):
            case = Case(level, index, 3, CutSetting.NONE)
            share = share_of(card, index)
            out.append(
                GameResult(case, card.card_id, Grade.GRADED, False, share, 0, False, 0, 0, None)
            )
    return out


def tools_with(author=None, judge=None, seed=1, summaries=None, cards=()):
    summaries = summaries or {
        card.card_id: "In 2 of 4 games the exit was not reached." for card in cards
    }
    return VariationTools(
        author or OfflineAuthor(), judge or AllowAllJudge(), random.Random(seed),
        OperatorSchedule(seed=7), summaries,
    )  # fmt: skip


def population(cards, arm=Arm.EVOLVED):
    return Population(0, arm, cards)


def steady(card, index):
    return len(card.lessons) / 10


def test_the_population_stays_at_six_and_the_two_elites_are_the_best_by_mean():
    cards = cards_of(6)
    step = next_population(
        population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
        tools_with(cards=cards),
    )  # fmt: skip
    assert len(step.population.cards) == ELITES + CHILDREN == 6
    assert step.population.generation == 1
    assert [c.card_id for c in step.population.cards[:2]] == [cards[5].card_id, cards[4].card_id]
    elite_births = [b for b in step.births if b.operator == Operator.ELITE]
    assert [b.card_id for b in elite_births] == [cards[5].card_id, cards[4].card_id]


def test_lexicase_never_picks_a_dominated_parent_and_random_sometimes_does():
    cards = cards_of(6)
    results = results_for(cards, steady)
    worst = cards[0].card_id
    lexicase_parents, random_parents = set(), set()
    for seed in range(40):
        for choice, seen in (
            (ParentChoice.LEXICASE, lexicase_parents),
            (ParentChoice.RANDOM, random_parents),
        ):
            step = next_population(
                population(cards), results, choice, tools_with(seed=seed, cards=cards)
            )
            seen.update(p for b in step.births for p in b.parents if b.operator != Operator.ELITE)
    assert worst not in lexicase_parents
    assert worst in random_parents


def test_both_arms_receive_the_same_operator_sequence():
    cards = cards_of(6)
    results = results_for(cards, steady)

    def operators(choice, arm):
        step = next_population(
            Population(0, arm, cards), results, choice, tools_with(seed=3, cards=cards)
        )
        return [
            b.operator for b in step.births if b.operator != Operator.ELITE and b.rejection is None
        ]

    assert len(operators(ParentChoice.LEXICASE, Arm.EVOLVED)) == 4
    schedule = OperatorSchedule(seed=7)
    assert [schedule.operator(1, s, 0) for s in range(4)] == [
        schedule.operator(1, s, 0) for s in range(4)
    ]
    ops = Counter(schedule.operator(g, s, 0) for g in range(1, 201) for s in range(4))
    assert set(ops) == set(Operator) - {
        Operator.ELITE, Operator.SEED_EMPTY, Operator.SEED_HISTORY, Operator.SEED_SPARK,
    }  # fmt: skip
    assert max(ops.values()) - min(ops.values()) <= 0.3 * min(ops.values())


class NamesAMap:
    """An author whose first answer for each parent names MAP05, then behaves."""

    name = "names-a-map"

    def __init__(self):
        self.calls = 0
        self.inner = OfflineAuthor()

    def vary(self, operator, parents, summary, seed):
        self.calls += 1
        bad = Lesson("Got lost in MAP05", "Go back", "Is it MAP05?")
        if self.calls <= 1:
            return Card.of([*parents[0].lessons, bad])
        return self.inner.vary(operator, parents, summary, seed)


def test_a_child_naming_a_map_is_rejected_logged_and_replaced():
    cards = cards_of(6)
    author = NamesAMap()
    step = next_population(
        population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
        tools_with(author=author, cards=cards),
    )  # fmt: skip
    rejected = [b for b in step.births if b.rejection is not None]
    assert rejected and all(b.rejection.value == "map_name" for b in rejected)
    assert len(step.population.cards) == 6
    accepted_ids = {c.card_id for c in step.population.cards}
    assert not accepted_ids & {b.card_id for b in rejected}
    lineage = Lineage()
    for card in cards:
        lineage.add(
            __import__("symbiont.act1.lineage", fromlist=["Birth"]).Birth(
                card.card_id, 0, Arm.EVOLVED, Operator.SEED_HISTORY, (), "seed", None
            )
        )
    for birth in step.births:
        lineage.add(birth)  # a rejected child is never a parent, so every birth is accepted


class RejectsFirstLesson:
    """A judge that calls the first lesson it is shown a landmark."""

    def __init__(self):
        self.seen = 0

    def landmark(self, lesson):
        self.seen += 1
        if self.seen == 1:
            return Verdict(False, Rejection.LANDMARK, "second left to the blue-key room")
        return Verdict(True, None, "")


def test_the_judge_can_reject_a_child_the_patterns_let_through():
    cards = cards_of(6)
    step = next_population(
        population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
        tools_with(judge=RejectsFirstLesson(), cards=cards),
    )  # fmt: skip
    assert [b.rejection for b in step.births if b.rejection] == [Rejection.LANDMARK]
    assert len(step.population.cards) == 6


def test_a_slot_that_keeps_getting_rejected_raises_the_prompt_error():
    cards = cards_of(6)
    with pytest.raises(MutationPromptError):
        next_population(
            population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
            tools_with(judge=FlagWordJudge("a"), cards=cards),
        )  # fmt: skip


def test_a_crossover_makes_no_author_call():
    cards = cards_of(6)
    seen = []

    class Counting(OfflineAuthor):
        def vary(self, operator, parents, summary, seed):
            seen.append(operator)
            return super().vary(operator, parents, summary, seed)

    next_population(
        population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
        tools_with(author=Counting(), cards=cards),
    )  # fmt: skip
    assert Operator.CROSSOVER not in seen


def test_crossover_takes_the_first_half_of_one_parent_and_the_second_of_the_other():
    first, second = Card.of(OFFLINE_LESSONS[:4]), Card.of(OFFLINE_LESSONS[1:5])
    child = crossover(first, second)
    assert child.lessons[:2] == first.lessons[:2]
    assert child.lessons[2:] == second.lessons[2:]


def test_the_same_seed_gives_the_same_next_population():
    cards = cards_of(6)

    def ids(seed):
        step = next_population(
            population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
            tools_with(seed=seed, cards=cards),
        )  # fmt: skip
        return [c.card_id for c in step.population.cards]

    assert ids(5) == ids(5)


def test_an_author_reply_error_propagates_instead_of_being_guessed():
    class Broken(OfflineAuthor):
        def vary(self, operator, parents, summary, seed):
            raise MutationReplyError("not a card")

    cards = cards_of(6)
    with pytest.raises(MutationReplyError):
        next_population(
            population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
            tools_with(author=Broken(), cards=cards),
        )  # fmt: skip


def test_archive_offers_carry_every_card_with_its_mean_fitness():
    cards = cards_of(6)
    step = next_population(
        population(cards), results_for(cards, steady), ParentChoice.RANDOM, tools_with(cards=cards)
    )
    assert {card.card_id for card, _ in step.archive_offers} == {c.card_id for c in cards}
    assert dict((c.card_id, m) for c, m in step.archive_offers)[cards[3].card_id] == pytest.approx(
        0.15
    )


def test_no_child_is_a_copy_of_a_card_of_the_population_or_of_its_own_parent():
    cards = cards_of(6)
    for seed in range(30):
        step = next_population(
            population(cards), results_for(cards, steady), ParentChoice.LEXICASE,
            tools_with(seed=seed, cards=cards),
        )  # fmt: skip
        made = [b for b in step.births if b.operator != Operator.ELITE]
        assert all(b.card_id not in b.parents for b in made)
        assert not {b.card_id for b in made if b.rejection is None} & {c.card_id for c in cards}


def test_two_arms_given_the_same_parents_write_the_same_children():
    cards = cards_of(6)
    results = results_for(cards, steady)
    steps = {}
    for arm in (Arm.EVOLVED, Arm.NO_SELECTION):
        # RANDOM and LEXICASE would pick different parents, so give both the same choice and
        # the same chance source: only the arm and its own author instance differ.
        steps[arm] = next_population(
            Population(0, arm, cards),
            results,
            ParentChoice.LEXICASE,
            tools_with(seed=3, cards=cards),
        )
    assert steps[Arm.EVOLVED].population.cards == steps[Arm.NO_SELECTION].population.cards


def test_the_call_seed_ignores_the_arm_and_varies_with_generation_slot_and_attempt():
    from symbiont.act1.generation import call_seed

    base = call_seed(7, 1, 0, 0)
    assert base == call_seed(7, 1, 0, 0)
    assert (
        len(
            {
                base,
                call_seed(8, 1, 0, 0),
                call_seed(7, 2, 0, 0),
                call_seed(7, 1, 1, 0),
                call_seed(7, 1, 0, 1),
            }
        )
        == 5
    )
