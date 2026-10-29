"""The paired summary: counts per arm, and a missing arm is an error, never zero."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "act1" / "summarize_pairs.py"
spec = importlib.util.spec_from_file_location("summarize_pairs", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def summary(policy, seed=3, ended="exited", pains=None):
    return {
        "level": "MAP02",
        "policy": policy,
        "seed": seed,
        "pains": {"wasted_move": 4} if pains is None else pains,
        "decisions": 9,
        "ended": ended,
        "tokens_in": 100,
        "tokens_out": 50,
    }


def test_a_pair_reports_both_arms_side_by_side():
    rows = module.pair_rows(
        [summary("glimmer_personal", pains={"wall_bump": 1}), summary("glimmer_plain")]
    )
    assert rows[0]["plain"]["pain_total"] == 4
    assert rows[0]["personal"]["pain_total"] == 1
    assert rows[0]["personal"]["exited"] and rows[0]["plain"]["tokens"] == 150


def test_a_lone_arm_is_an_error_not_zero_pain():
    with pytest.raises(ValueError, match="needs both arms"):
        module.pair_rows([summary("glimmer_plain")])


def test_a_duplicate_arm_is_an_error():
    with pytest.raises(ValueError, match="twice"):
        module.pair_rows([summary("glimmer_plain"), summary("glimmer_plain")])


def test_the_prereg_line_is_not_an_episode(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps({"scored": "p.md", "prereg_sha256": "x"})
        + "\n"
        + json.dumps(summary("glimmer_plain"))
        + "\n"
    )
    assert len(module.read_summaries([path])) == 1
