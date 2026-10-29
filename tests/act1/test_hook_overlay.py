"""The clip panel can only say what the tagger said, and every tag has a plain-words label."""

import pytest

from symbiont.act1.env_text import GameStateView, Layout
from symbiont.act1.game_pains import GamePain
from symbiont.act1.hook_overlay import BANNER_FRAMES, PAIN_LABELS, banner_start, card_for, tally
from symbiont.act1.steplog import MoveKind, MoveRun


def a_run(label="go_to(door)", outcome="arrived"):
    view = GameStateView(
        health=100.0, ammo=50.0, position=(0.0, 0.0), angle_deg=0.0, objects=(), doors=(),
        keys_held=(), layout=Layout(True, True, True, False), exits=(), closed_sectors=frozenset(),
    )  # fmt: skip
    return MoveRun(0, label, MoveKind.WALK, outcome, 5, view, view)


def test_every_pain_the_tagger_can_fire_has_a_label():
    assert set(PAIN_LABELS) == set(GamePain)


def test_the_four_labels_read_as_plain_words():
    assert list(PAIN_LABELS.values()) == [
        "wall bump", "room re-entered", "room re-checked", "wasted move",
    ]  # fmt: skip


def test_a_card_carries_the_move_and_exactly_the_tagged_pains():
    card = card_for(7, a_run(), [GamePain.WALL_BUMP, GamePain.WASTED_MOVE])
    assert (card.step, card.move, card.pains) == (7, "go_to(door)", ("wall bump", "wasted move"))


def test_an_untagged_move_has_no_pain_label():
    assert card_for(0, a_run(), []).pains == ()


def test_an_unlabeled_pain_raises_instead_of_printing_a_raw_value():
    with pytest.raises(KeyError):
        card_for(0, a_run(), ["made_up"])


def test_the_banner_covers_the_last_frames_of_a_move_and_all_of_a_short_one():
    assert banner_start(100) == 100 - BANNER_FRAMES
    assert banner_start(5) == 0


def test_the_tally_counts_labels_across_cards():
    cards = [
        card_for(0, a_run(), [GamePain.WALL_BUMP]),
        card_for(1, a_run(), [GamePain.WALL_BUMP, GamePain.WASTED_MOVE]),
    ]
    assert tally(cards) == {"wall bump": 2, "wasted move": 1}
