"""The run driver: a dry run finishes, a killed run resumes, Spark needs a frozen prereg."""

import json
import random
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


def test_the_fake_player_without_dry_run_is_refused_not_published_as_exploratory(tmp_path):
    args = run_evolve.parse_arguments(
        ["--run", "r", "--player", "fake", "--generations", "1", "--root", str(tmp_path)]
    )
    with pytest.raises(run_evolve.FakePlayerNeedsDryRunError):
        run_evolve.run(args)
    assert not (tmp_path / "r").exists()


def test_the_dry_run_output_says_simulated_at_the_top_and_the_bottom(tmp_path, capsys):
    argv = ["--run", "r", "--player", "fake", "--generations", "1", "--root", str(tmp_path)]
    run_evolve.main([*argv, "--dry-run"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("SIMULATED") and lines[-1].startswith("SIMULATED")


class Wobbly(fake_author.OfflineAuthor):
    """An author that is not deterministic: it ignores the seed and rolls its own dice."""

    def vary(self, operator, parents, summary, seed):
        return super().vary(operator, parents, summary, random.getrandbits(32))


def test_a_resume_reuses_the_stored_children_even_when_the_author_would_write_new_ones(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        run_evolve, "build_tools", lambda author, seed: run_evolve_tools(Wobbly(), seed)
    )
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: Watching(die_on=40))
    with pytest.raises(KilledError):
        run_evolve.run(args_for(tmp_path))
    stored = json.loads((tmp_path / "r1" / "state.json").read_text())["generations"]
    assert set(stored) == {"evolved:1"}  # written before the first game of generation 1
    monkeypatch.setattr(run_evolve, "build_player", lambda *_: Watching())
    resumed = run_evolve.run(args_for(tmp_path))
    kept = {b["card_id"] for b in stored["evolved:1"]["births"]}
    assert kept <= {b.card_id for b in resumed.births}


def run_evolve_tools(author, seed):
    import random

    from symbiont.act1.generation import OperatorSchedule, VariationTools

    return VariationTools(
        author, fake_author.AllowAllJudge(), random.Random(seed), OperatorSchedule(seed), {}
    )


def test_a_resume_with_a_different_player_or_model_is_refused(tmp_path):
    run_evolve.run(args_for(tmp_path))
    with pytest.raises(run_evolve.PlayerChangedError):
        run_evolve.run(args_for(tmp_path, more=["--model", "other-model"]))
    with pytest.raises(run_evolve.PlayerChangedError):
        run_evolve.run(args_for(tmp_path, more=["--reasoning", "high"]))


def test_every_stored_game_says_who_played_it(tmp_path):
    run_evolve.run(args_for(tmp_path, more=["--model", "m1", "--reasoning", "low"]))
    games = json.loads((tmp_path / "r1" / "state.json").read_text())["games"]
    assert games
    assert {json.dumps(g["player"], sort_keys=True) for g in games.values()} == {
        json.dumps(
            {"player": "fake", "author": "fake", "model": "m1", "reasoning": "low"}, sort_keys=True
        )
    }


def test_the_summary_spend_comes_from_the_ledger_snapshot(tmp_path):
    run_evolve.run(args_for(tmp_path))
    summary = json.loads((tmp_path / "r1" / "summary.json").read_text())
    assert summary["spend"] == run_evolve.NullLedger().snapshot()


def test_the_same_seed_gives_identical_output_under_different_hash_seeds(tmp_path):
    import os
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "evolve" / "run_evolve.py"
    outputs = []
    for hash_seed in ("1", "2", "random"):
        root = tmp_path / hash_seed
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        argv = [sys.executable, str(script), "--run", "d", "--player", "fake", "--dry-run"]
        done = subprocess.run(
            [*argv, "--generations", "3", "--root", str(root)],
            env=env, capture_output=True, text=True, check=True,
        )  # fmt: skip
        summary = json.loads((root / "d" / "summary.json").read_text())
        outputs.append((done.stdout, summary["curves"], summary["picks"], summary["births"]))
    assert outputs[0] == outputs[1] == outputs[2]
