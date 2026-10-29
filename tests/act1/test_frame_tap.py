"""FrameTap keeps frames from real actions only and ends the episode at its budget."""

from types import SimpleNamespace

import numpy as np
import pytest

from symbiont.act1.frame_tap import FrameTap


class StubGame:
    def __init__(self, screens_until_end=None):
        self.actions = []
        self.ended_after = screens_until_end
        self.player = "stub"

    def make_action(self, action):
        self.actions.append(action)
        return 0.0

    def get_state(self):
        if self.ended_after is not None and len(self.actions) >= self.ended_after:
            return None
        return SimpleNamespace(screen_buffer=np.full((3, 2, 2), len(self.actions), dtype=np.uint8))

    def is_episode_finished(self):
        return self.ended_after is not None and len(self.actions) >= self.ended_after


def test_every_stride_th_action_keeps_a_frame():
    tap = FrameTap(StubGame(), stride=2, tic_budget=100)
    for _ in range(5):
        tap.make_action([0])
    assert [int(frame[0, 0, 0]) for frame in tap.take_frames()] == [2, 4]


def test_taking_frames_hands_them_over_once():
    tap = FrameTap(StubGame(), stride=1, tic_budget=100)
    tap.make_action([0])
    assert len(tap.take_frames()) == 1
    assert tap.take_frames() == []


def test_the_budget_ends_the_episode_and_says_it_was_the_budget():
    tap = FrameTap(StubGame(), stride=1, tic_budget=3)
    for _ in range(3):
        assert not tap.is_episode_finished() or tap.budget_spent
        tap.make_action([0])
    assert tap.is_episode_finished() and tap.budget_spent


def test_a_game_that_ends_first_is_not_reported_as_a_spent_budget():
    tap = FrameTap(StubGame(screens_until_end=2), stride=1, tic_budget=100)
    tap.make_action([0])
    tap.make_action([0])
    assert tap.is_episode_finished() and not tap.budget_spent
    assert len(tap.take_frames()) == 1  # the action that ended the episode left no screen


def test_other_game_attributes_pass_through():
    assert FrameTap(StubGame(), stride=1, tic_budget=1).player == "stub"


def test_a_zero_stride_raises():
    with pytest.raises(ValueError, match="at least 1"):
        FrameTap(StubGame(), stride=0, tic_budget=1)
