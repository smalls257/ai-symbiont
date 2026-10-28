"""The T39 runner end to end on synthetic episodes, and its refusal to score the scoring fold.

Violation prevented: **Paper Tiger** (a pipeline whose parts pass alone but do not join up)
and the hold-out rule (the scoring fold read by an exploratory run).
"""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "offline"


@pytest.fixture(scope="module")
def runner():
    """The runner, importable by name so forked workers can unpickle its jobs."""
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_meta_start", SCRIPTS / "run_meta_start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_meta_start"] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("run_meta_start", None)
        sys.path.remove(str(SCRIPTS))


def synthetic(tmp_path):
    """25 repositories of 12 short sessions where feature 3 marks trouble ahead."""
    rng = np.random.default_rng(0)
    repos = [f"org/r{i:02d}" for i in range(25)]
    arrays = {}
    for i, _ in enumerate(repos):
        x = (rng.random((12 * 8, 86)) < 0.15).astype(np.float64)
        arrays |= {
            f"{i}.x": x,
            f"{i}.y": x[:, 3] > 0,
            f"{i}.b": np.ones(len(x), dtype=bool),
            f"{i}.n": np.full(12, 8),
            f"{i}.c": rng.random(len(x)),
        }
    episodes = tmp_path / "episodes.npz"
    np.savez(episodes, repos=np.array(repos), **arrays)
    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps({"repos": [{"repo": r, "fold": i % 5} for i, r in enumerate(repos)]})
    )
    return str(episodes), str(pool)


def test_train_then_score_validation_writes_every_row(runner, tmp_path):
    episodes, pool = synthetic(tmp_path)
    starts = str(tmp_path / "starts.npz")
    common = ["--episodes", episodes, "--pool", pool]
    runner.main(
        ["train", *common, "--out", starts, "--seeds", "0", "--rates", "0.03"]
        + ["--outer-steps", "20", "--train-repos", "5", "--workers", "2"]
    )
    out = tmp_path / "result.json"
    runner.main(["score", *common, "--starts", starts, "--on", "validation", "--out", str(out)])
    document = json.loads(out.read_text())
    assert document["run_label"] == "exploratory"
    assert document["evaluated_on"] == "validation"
    assert document["split"] == {"train": 10, "validation": 10, "scoring": 5}
    arms = {r["arm"] for r in document["rows"]}
    assert {"fly meta start", "dense cold start", "logistic + online calibrator"} <= arms
    assert {c["filler"] for c in document["chosen_starts"]} == {"fly", "dense"}


def test_the_scoring_fold_is_refused_without_a_scored_run(runner, tmp_path):
    episodes, pool = synthetic(tmp_path)
    with pytest.raises(SystemExit, match="scored"):
        runner.main(
            ["score", "--episodes", episodes, "--pool", pool, "--starts", "x.npz"]
            + ["--on", "scoring", "--out", str(tmp_path / "r.json")]
        )


def test_only_the_fly_and_densenet_are_meta_trained(runner):
    assert runner.filler_of("fly", 1).name == "mushroom"
    assert runner.filler_of("dense", 2).lr == runner.DENSE_RATE
    with pytest.raises(ValueError, match="counters"):
        runner.filler_of("counters", 0)
