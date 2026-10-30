"""The held-out test's cases, declared-file check and scorer: no engine, no model."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import fired_outcomes as fo  # noqa: E402
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


def fired(first_mistakes, first_progress=0.0, progress=0.0, no_progress=0):
    return hs.Fired(2, first_mistakes, first_progress, first_mistakes, progress, no_progress)


def synthetic(lessons_gain, count=240, progress_gain=0.0):
    """Cases on 40 maps; lessons lower first-fire mistakes by `lessons_gain` and move progress."""
    cases = {case(f"OB{n % 40 + 1:04d}", 4000 + n) for n in range(count)}
    wobble = {c: ((c.seed % 7) - 3) * 0.1 for c in cases}
    arms = {
        hc.Arm.NONE: {c: fired(1.0 + wobble[c], wobble[c] * 50) for c in cases},
        hc.Arm.ONE_MOVE: {c: None for c in cases},
        hc.Arm.LESSONS: {
            c: fired(1.0 + wobble[c] - lessons_gain, wobble[c] * 50 + progress_gain) for c in cases
        },
    }
    return cases, {arm: {c: 0.0 for c in cases} for arm in hc.Arm}, arms


def c1(cases, fitness, arms):
    return hs.analyze(cases, fitness, arms)["sets"]["generated"]["C1_lessons_at_first_fire"]


def test_a_clear_gain_at_the_first_fire_is_supported():
    assert c1(*synthetic(lessons_gain=0.5))["verdict"] == "supported"


def test_no_difference_is_a_tie():
    assert c1(*synthetic(lessons_gain=0.0))["verdict"] == "tie"


def test_fewer_mistakes_but_worse_progress_is_worse_not_supported():
    result = c1(*synthetic(lessons_gain=0.5, progress_gain=-100.0))
    assert result["progress"]["word"] == "worse" and result["verdict"] == "worse"


def test_fewer_than_126_cases_with_a_fire_is_underpowered_in_words():
    cases, fitness, arms = synthetic(lessons_gain=0.5, count=120)
    assert c1(cases, fitness, arms)["verdict"] == "underpowered"
    sentence = hs.analyze(cases, fitness, arms)["result"]
    assert "underpowered" in sentence and "126" in sentence


def test_one_move_better_but_small_is_named():
    assert hs.one_move_verdict({"word": "better", "mean_difference": 0.05}) == "better but small"
    assert hs.one_move_verdict({"word": "better", "mean_difference": 0.09}) == "supported"
    assert hs.one_move_verdict({"word": "worse", "mean_difference": -0.2}) == "worse"
    assert hs.one_move_verdict({"word": "tie", "mean_difference": 0.0}) == "tie"


def test_missing_progress_is_dropped_not_scored_as_zero():
    cases, fitness, arms = synthetic(lessons_gain=0.5)
    victim = sorted(cases, key=lambda each: each.seed)[0]
    arms[hc.Arm.LESSONS][victim] = fired(1.0, None, None, no_progress=2)
    result = c1(cases, fitness, arms)
    assert result["progress"]["cases"] == len(cases) - 1
    counts = hs.analyze(cases, fitness, arms)["sets"]["generated"]["fires_without_progress_reading"]
    assert counts["lessons"] == 2


def test_progress_over_drops_a_fire_with_no_window_and_a_missing_route():
    outcomes = [
        fo.DecisionOutcome(0, 10.0),
        fo.DecisionOutcome(0, None),
        fo.DecisionOutcome(0, 4.0),
    ]
    assert fo.progress_over(outcomes, 2) is None  # last decision: no window
    assert fo.progress_over(outcomes, 1) is None  # no route reading at the start
    cut = [fo.DecisionOutcome(0, 10.0), fo.DecisionOutcome(0, 6.0)]
    assert fo.progress_over(cut, 0) == 4.0  # window cut by the game's end runs to its last decision


def test_more_than_ten_percent_dropped_is_refused():
    from symbiont.act1.game_fitness import GameResult, Grade

    cases = [case("OB0001", 4000 + n) for n in range(10)]

    def result(each, grade):
        return GameResult(each, "x", grade, False, 0.0, 0, False, 0, 0, None)

    ungraded = {c: result(c, Grade.UNGRADED if c.seed < 4002 else Grade.GRADED) for c in cases}
    with pytest.raises(ht.final_test.IncompleteRunError):
        ht.final_test.drop_incomplete({"none": ungraded}, cases)
