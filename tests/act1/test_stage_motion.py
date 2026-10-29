"""The motion rules: events exist only because a real counter changed, and they age out."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts" / "act1"))
motion = importlib.import_module("stage_motion")

from symbiont.act1.hook_overlay import PlayerStats  # noqa: E402


def stats(health=100, kills=0, dealt=0, taken=0):
    return PlayerStats(health, 0, 50, kills, dealt, taken, 0, 0, False)


def test_a_kill_pops_then_settles():
    clock = motion.EventClock()
    clock.tick(stats())
    popped = clock.tick(stats(kills=1))
    assert popped.kill.amount == 1 and motion.pop_scale(popped.kill) == pytest.approx(1.5)
    for _ in range(motion.POP_FRAMES + 1):
        settled = clock.tick(stats(kills=1))
    assert motion.pop_scale(settled.kill) == 1.0


def test_no_counter_change_means_no_event():
    clock = motion.EventClock()
    clock.tick(stats())
    quiet = clock.tick(stats())
    assert quiet == motion.Events()
    assert motion.pulse_strength(quiet.hurt) == 0.0


def test_damage_shows_amounts_and_fades_out_after_its_window():
    clock = motion.EventClock()
    clock.tick(stats())
    hit = clock.tick(stats(health=88, dealt=30, taken=12))
    assert (hit.hurt.amount, hit.taken.amount, hit.dealt.amount) == (12, 12, 30)
    for _ in range(motion.FLOAT_FRAMES + 1):
        gone = clock.tick(stats(health=88, dealt=30, taken=12))
    assert gone.taken is None and motion.float_progress(gone.taken) is None


def test_the_banner_holds_for_the_last_second_only():
    assert motion.banner_on(motion.BANNER_FRAMES) and not motion.banner_on(motion.BANNER_FRAMES + 1)


def test_a_bar_clamps_and_refuses_a_zero_maximum():
    assert motion.bar_fill(150, 100) == 1.0 and motion.bar_fill(-5, 100) == 0.0
    with pytest.raises(ValueError, match="positive maximum"):
        motion.bar_fill(1, 0)
