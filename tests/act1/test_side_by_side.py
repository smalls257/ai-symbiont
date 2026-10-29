"""The evidence clips' honest parts: outcome words, totals over every episode, pair checks."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[2] / "scripts" / "act1"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "side_by_side_under_test", SCRIPTS / "side_by_side.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sidecar(ended="decision_cap", decisions=16, pains=None, seed=3, level="MAP02"):
    return {"ended": ended, "decisions": decisions, "pains": pains or {}, "seed": seed,
            "level": level, "fps": 30, "spans": {}}  # fmt: skip


def test_the_outcome_says_the_decision_of_the_exit_or_that_there_was_none():
    assert module.outcome_text(sidecar("exited", 9), 16) == "exit reached at decision 9"
    assert module.outcome_text(sidecar(), 16) == "no exit within 16 decisions"
    assert "died" in module.outcome_text(sidecar("died", 5), 16)


def test_the_footer_shows_the_outcome_only_after_the_last_decision():
    done = sidecar("exited", 3)
    assert module.footer_text(done, 1, 16) == "decision 2 of 16"
    assert module.footer_text(done, 2, 16) == "exit reached at decision 3"


def test_totals_cover_every_episode_not_the_shown_one():
    first = sidecar("exited", 9, {"wall_bump": 2})
    second = sidecar(pains={"wall_bump": 1, "wasted_move": 4})
    total = module.totals([first, second])
    assert (total["episodes"], total["pain_total"], total["exits"], total["decisions"]) == (
        2,
        7,
        1,
        25,
    )
    assert total["pains"]["wall_bump"] == 3 and total["pains"]["room_reentered"] == 0


def arm(**fields):
    return module.Arm(sidecar(**fields), Path("x.mp4"), "title")


def test_a_pair_must_share_level_and_by_default_seed():
    with pytest.raises(ValueError, match="one level"):
        module.check_pair(arm(), arm(level="MAP03"), "same")
    with pytest.raises(ValueError, match="one seed"):
        module.check_pair(arm(), arm(seed=4), "same")
    module.check_pair(arm(), arm(seed=4), "named_in_titles")


def test_a_missing_sidecar_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        module.load_arm(str(tmp_path / "none.json"), "t")


def test_the_shorter_segment_holds_its_last_frame():
    long, short = [1, 2, 3], [9]
    held = [0, 0]
    assert list(module.synced_halves([long, short], held)) == [(1, 9), (2, 9), (3, 9)]
