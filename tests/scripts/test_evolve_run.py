"""The run driver: a dry run finishes, a killed run resumes, Spark needs a frozen prereg."""

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import fake_author  # noqa: E402 - needs the scripts path added above
import fake_player  # noqa: E402
import run_evolve  # noqa: E402

from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.levels import LevelSplit, levels_in  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.eval.prereg import PreregNotFrozenError  # noqa: E402

pytestmark = pytest.mark.periphery
HELD_OUT = set(levels_in(LevelSplit.HELD_OUT))


class KilledError(Exception):
    """Stands in for a crash or a Ctrl-C in the middle of a run."""


class Watching:
    """Wraps the hidden-rule player: records games, optionally dies on the Nth."""

    def __init__(self, die_on=None):
        self.inner, self.die_on, self.keys = fake_player.HiddenRulePlayer(), die_on, []

    def play(self, card, case):
        if self.die_on is not None and len(self.keys) + 1 == self.die_on:
            raise KilledError
        self.keys.append(run_evolve.game_key(card.card_id, case))
        return self.inner.play(card, case)


def args_for(tmp_path, **extra):
    base = ["--run", "r1", "--player", "fake", "--generations", "2", "--root", str(tmp_path)]
    return run_evolve.parse_arguments([*base, "--dry-run", *extra.get("more", [])])


def test_a_two_generation_dry_run_finishes_and_writes_state_events_and_summary(tmp_path):
    record = run_evolve.run(args_for(tmp_path))
    assert record.stop_reason is None and record.last_played == 2
    directory = tmp_path / "r1"
    assert stat.S_IMODE((directory / "state.json").stat().st_mode) == 0o600
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    games = [e for e in events if e["event"] == "game"]
    assert games and all("seconds" in e and "grade" in e for e in games)
    assert events[0]["event"] == "start" and events[-1]["event"] == "end"
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["label"] == "dry run, fake player" and summary["claim"] == "exploratory"
    assert summary["floor"] is not None


def test_a_killed_run_resumes_without_replaying_a_finished_game(tmp_path, monkeypatch):
    first = Watching(die_on=5)
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: first)
    with pytest.raises(KilledError):
        run_evolve.run(args_for(tmp_path))
    assert len(first.keys) == 4
    second = Watching()
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: second)
    run_evolve.run(args_for(tmp_path))
    assert set(first.keys).isdisjoint(second.keys)
    uninterrupted = Watching()
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: uninterrupted)
    run_evolve.run(args_for(tmp_path / "other"))
    assert len(first.keys) + len(second.keys) == len(uninterrupted.keys)


def test_a_resumed_run_reaches_the_same_record_as_an_uninterrupted_one(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: Watching(die_on=7))
    with pytest.raises(KilledError):
        run_evolve.run(args_for(tmp_path))
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: Watching())
    resumed = run_evolve.run(args_for(tmp_path))
    fresh = run_evolve.run(args_for(tmp_path / "other"))
    assert resumed.picks == fresh.picks and resumed.gaps == fresh.gaps


def test_the_spark_player_after_generation_zero_needs_a_frozen_prereg(tmp_path):
    spark = run_evolve.parse_arguments(
        ["--run", "r", "--player", "spark", "--generations", "1", "--root", str(tmp_path)]
    )
    with pytest.raises(PreregNotFrozenError):
        run_evolve.run(spark)
    draft = tmp_path / "draft.md"
    draft.write_text("# x\n\n**DRAFT, not frozen**\n")
    with pytest.raises(PreregNotFrozenError):
        run_evolve.require_scored_ready(run_evolve.PlayerKind.SPARK, 1, draft)


def test_spark_at_generation_zero_passes_the_prereg_guard_then_stops_as_not_built(tmp_path):
    run_evolve.require_scored_ready(run_evolve.PlayerKind.SPARK, 0, None)
    zero = run_evolve.parse_arguments(
        ["--run", "r", "--player", "spark", "--generations", "0", "--root", str(tmp_path)]
    )
    with pytest.raises(run_evolve.SparkNotBuiltError):
        run_evolve.run(zero)


def test_no_held_out_level_is_played(tmp_path, monkeypatch):
    watching = Watching()
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: watching)
    run_evolve.run(args_for(tmp_path))
    levels = {key.split("|")[1] for key in watching.keys}
    assert levels and HELD_OUT.isdisjoint(levels)


def test_a_game_result_survives_the_json_round_trip():
    case = Case("MAP02", 5, 4, CutSetting.TEN_PERCENT)
    result = GameResult(
        case,
        "abc",
        Grade.UNGRADED,
        False,
        0.0,
        2,
        False,
        1,
        3,
        "GlimmerReplyError",
        (("wall_bump", 2),),
    )
    assert (
        run_evolve.result_from_json(json.loads(json.dumps(run_evolve.result_to_json(result))))
        == result
    )


def test_the_dry_run_seed_cards_are_six_distinct_cards_starting_with_the_empty_one():
    cards = fake_author.dry_run_seed_cards()
    assert len({c.card_id for c in cards}) == 6 and cards[0].lessons == ()
