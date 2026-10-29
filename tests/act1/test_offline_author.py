"""The offline author and judges: deterministic edits, no model."""

import pytest

from symbiont.act1.card_genome import Card
from symbiont.act1.generation import MutationReplyError
from symbiont.act1.lineage import Operator
from symbiont.act1.offline_author import (
    OFFLINE_LESSONS,
    AllowAllJudge,
    FlagWordJudge,
    OfflineAuthor,
)

PARENT = Card.of(OFFLINE_LESSONS[:3])


def test_add_grows_the_card_and_the_same_start_gives_the_same_child():
    one, two = OfflineAuthor(), OfflineAuthor()
    child = one.vary(Operator.ADD, (PARENT,), "summary")
    assert len(child.lessons) == 4
    assert child == two.vary(Operator.ADD, (PARENT,), "summary")


def test_repeated_asks_about_one_parent_give_different_children():
    author = OfflineAuthor()
    assert author.vary(Operator.ADD, (PARENT,), "s") != author.vary(Operator.ADD, (PARENT,), "s")


def test_delete_merge_and_rewrite_edit_a_lesson_each():
    author = OfflineAuthor()
    assert len(author.vary(Operator.DELETE, (PARENT,), "s").lessons) == 2
    assert len(author.vary(Operator.MERGE, (PARENT,), "s").lessons) == 2
    assert author.vary(Operator.REWRITE, (PARENT,), "s").lessons[1:] == PARENT.lessons[1:]


def test_an_edit_that_cannot_apply_to_an_empty_card_leaves_it_empty():
    assert OfflineAuthor().vary(Operator.DELETE, (Card.of([]),), "s").lessons == ()


def test_crossover_is_not_an_authors_job_and_raises():
    with pytest.raises(MutationReplyError, match="crossover"):
        OfflineAuthor().vary(Operator.CROSSOVER, (PARENT, PARENT), "s")


def test_the_judges_call_a_landmark_only_when_told_to():
    assert AllowAllJudge().landmark(OFFLINE_LESSONS[0]).general
    assert not FlagWordJudge("enemy").landmark(OFFLINE_LESSONS[1]).general
    assert FlagWordJudge("enemy").landmark(OFFLINE_LESSONS[0]).general
