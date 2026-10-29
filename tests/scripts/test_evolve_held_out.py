"""The held-out test's cases, declared-file check and scorer: no engine, no model."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import held_out_cases as hc  # noqa: E402 - needs the scripts path added above
import held_out_score as hs  # noqa: E402
import held_out_test as ht  # noqa: E402

from symbiont.act1.game_fitness import Case  # noqa: E402
from symbiont.act1.move_cuts import NORMAL_SKILL, CutSetting  # noqa: E402

pytestmark = pytest.mark.periphery


def kept_file(tmp_path, count=40):
    path = tmp_path / "kept.json"
    path.write_text(json.dumps({"kept": [f"OB{n:04d}" for n in range(1, count + 1)]}))
    return path


def test_cases_are_425_with_no_repeat(tmp_path):
    cases = hc.all_cases(kept_file(tmp_path))
    assert len(cases) == 40 * 9 + 13 * 5
    assert len({(c.level, c.seed) for c in cases}) == len(cases)


def test_wrong_map_count_is_refused(tmp_path):
    with pytest.raises(hc.WrongMapCountError):
        hc.generated_maps(kept_file(tmp_path, count=39))


def test_changed_map_file_is_refused(tmp_path):
    (tmp_path / "ob0001.wad").write_bytes(b"changed")
    declaration = tmp_path / "decl.md"
    declaration.write_text(f"OB0001 seed=7001 size=tiny file_sha256={'0' * 64}\n")
    with pytest.raises(hc.MapFileMismatchError):
        hc.require_declared_files(("OB0001",), tmp_path, declaration)


def test_declared_map_file_passes(tmp_path):
    data = b"wad bytes"
    (tmp_path / "ob0001.wad").write_bytes(data)
    declaration = tmp_path / "decl.md"
    declaration.write_text(
        f"OB0001 seed=7001 size=tiny file_sha256={hashlib.sha256(data).hexdigest()}\n"
    )
    hc.require_declared_files(("OB0001",), tmp_path, declaration)


def test_missing_quote_in_the_prereg_is_refused():
    with pytest.raises(ht.PreregMismatchError):
        ht.quoted(ht.CUTOFF_QUOTE, "no cutoff here", "cutoff")


def test_none_arm_computes_fires_and_shows_nothing():
    none = hc.ARM_SETTINGS[hc.Arm.NONE]
    assert none.delivery == hc.lesson_players.Delivery.NOTHING and not none.card.lessons
    assert hc.ARM_SETTINGS[hc.Arm.LESSONS].delivery == hc.lesson_players.Delivery.ADVICE


def case(level, seed):
    return Case(level, seed, NORMAL_SKILL, CutSetting.NONE)


def synthetic(lessons_gain, count=120):
    """Cases on 40 maps; lessons change mistakes at fires by `lessons_gain` per fired decision."""
    cases = {case(f"OB{n % 40 + 1:04d}", 4000 + n) for n in range(count)}
    wobble = {c: ((hash(c.seed) % 7) - 3) * 0.1 for c in cases}
    fired = {
        hc.Arm.NONE: {c: hs.Fired(2, 1.0 + wobble[c], 0.0) for c in cases},
        hc.Arm.ONE_MOVE: {c: None for c in cases},
        hc.Arm.LESSONS: {c: hs.Fired(2, 1.0 + wobble[c] - lessons_gain, 0.0) for c in cases},
    }
    fitness = {arm: {c: 0.0 for c in cases} for arm in hc.Arm}
    return cases, fitness, fired


def test_a_clear_gain_at_fires_is_supported():
    cases, fitness, fired = synthetic(lessons_gain=0.5)
    result = hs.analyze(cases, fitness, fired)["sets"]["generated"]["C1_lessons_at_fires"]
    assert result["verdict"] == "supported"


def test_no_difference_is_a_tie():
    cases, fitness, fired = synthetic(lessons_gain=0.0)
    result = hs.analyze(cases, fitness, fired)["sets"]["generated"]["C1_lessons_at_fires"]
    assert result["verdict"] == "tie"


def test_too_few_cases_with_a_fire_is_underpowered():
    cases, fitness, fired = synthetic(lessons_gain=0.5, count=40)
    result = hs.analyze(cases, fitness, fired)["sets"]["generated"]["C1_lessons_at_fires"]
    assert result["verdict"] == "underpowered"


def test_one_move_needs_the_minimum_gain():
    assert hs.one_move_verdict({"word": "better", "mean_difference": 0.05}) == "tie"
    assert hs.one_move_verdict({"word": "better", "mean_difference": 0.09}) == "supported"
    assert hs.one_move_verdict({"word": "worse", "mean_difference": -0.2}) == "worse"
