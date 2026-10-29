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
        ["train", *common, "--out", starts, "--seeds", "0"]
        + ["--outer-steps", "20", "--train-repos", "5", "--workers", "4"]
        + ["--calibrator-rates", "0.1", "0.5"]
    )
    out = tmp_path / "result.json"
    runner.main(["score", *common, "--starts", starts, "--on", "validation", "--out", str(out)])
    document = json.loads(out.read_text())
    assert document["run_label"] == "exploratory"
    assert document["evaluated_on"] == "validation"
    assert document["split"] == {"train": 10, "validation": 10, "scoring": 5}
    arms = {r["arm"] for r in document["rows"]}
    assert {"fly meta start", "dense cold start", "logistic + online calibrator"} <= arms
    chosen = document["chosen_on_validation"]
    assert {c["filler"] for c in chosen["meta"]} == {"fly", "dense"}
    assert {c["calibrator_rate"] for c in chosen["cold"]} <= set(runner.CALIBRATOR_RATES)
    assert chosen["adapting_classifier"]["calibrator_rate"] in runner.CALIBRATOR_RATES


def test_the_held_out_repositories_are_refused_without_a_scored_run(tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_meta_start_scored", SCRIPTS / "run_meta_start_scored.py"
        )
        scored = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scored)
    finally:
        sys.path.remove(str(SCRIPTS))
    args = ["--episodes", "e", "--held-out", "h", "--pool", "p", "--starts", "s", "--out", "o"]
    with pytest.raises(SystemExit, match="scored"):
        scored.main(args)


def test_only_the_fly_and_densenet_are_meta_trained(runner):
    assert runner.filler_of("fly", 1, 0.1).calibrator_rate == 0.1
    assert runner.filler_of("dense", 2, 0.2).lr == runner.DENSE_RATE
    with pytest.raises(ValueError, match="counters"):
        runner.filler_of("counters", 0, 0.1)


def test_a_restarted_training_run_resumes_each_job_from_its_checkpoint(runner, tmp_path):
    episodes, pool = synthetic(tmp_path)
    starts = str(tmp_path / "starts.npz")
    args = ["train", "--episodes", episodes, "--pool", pool, "--out", starts, "--seeds", "0"]
    args += ["--outer-steps", "20", "--train-repos", "5", "--workers", "4"]
    args += ["--calibrator-rates", "0.5"]
    runner.main(args)
    first = dict(np.load(starts))
    jobs = tmp_path / "starts-jobs"
    for done in jobs.glob("*.done.json"):
        done.unlink()  # as if the machine died after the last check, before the job ended
    assert list(jobs.glob("*.progress.json"))
    runner.main(args)
    again = dict(np.load(starts))
    assert first.keys() == again.keys()
    for key in first:
        np.testing.assert_array_equal(first[key], again[key])


def held_out_file(tmp_path):
    """Three repositories of 14 sessions over 4 tasks, with task ids."""
    rng = np.random.default_rng(9)
    repos, arrays = ["x/pillow", "y/dvc", "z/conan"], {}
    for i, repo in enumerate(repos):
        x = (rng.random((14 * 8, 86)) < 0.15).astype(np.float64)
        arrays |= {
            f"{i}.x": x,
            f"{i}.y": x[:, 3] > 0,
            f"{i}.b": np.ones(len(x), dtype=bool),
            f"{i}.n": np.full(14, 8),
            f"{i}.c": rng.random(len(x)),
            f"{i}.t": np.array([f"{repo}-{k % 4}" for k in range(14)]),
        }
    path = tmp_path / "held.npz"
    np.savez(path, repos=np.array(repos), **arrays)
    path.with_suffix(".json").write_text(json.dumps({r: {"counts": {}} for r in repos}))
    return str(path)


def test_the_scored_runner_writes_both_sets_and_every_comparison(runner, tmp_path, monkeypatch):
    episodes, pool = synthetic(tmp_path)
    starts = str(tmp_path / "starts.npz")
    runner.main(
        ["train", "--episodes", episodes, "--pool", pool, "--out", starts, "--seeds", "0"]
        + ["--outer-steps", "10", "--train-repos", "5", "--workers", "4"]
        + ["--calibrator-rates", "0.1", "0.5"]
    )
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "run_meta_start_scored", SCRIPTS / "run_meta_start_scored.py"
    )
    scored = importlib.util.module_from_spec(spec)
    sys.modules["run_meta_start_scored"] = scored
    try:
        spec.loader.exec_module(scored)
        monkeypatch.setattr(scored, "run_provenance", lambda **_: {"run_label": "test"})
        out = tmp_path / "scored.json"
        scored.main(
            ["--episodes", episodes, "--held-out", held_out_file(tmp_path), "--pool", pool]
            + ["--starts", starts, "--out", str(out), "--scored", "--workers", "4"]
        )
    finally:
        sys.modules.pop("run_meta_start_scored", None)
        sys.path.remove(str(SCRIPTS))
    document = json.loads(out.read_text())
    primary = document["primary_held_out"]
    assert primary["windows"]["first 10 sessions"]["unit"] == "session"
    assert primary["windows"]["first 10 sessions"]["units"] == 30
    assert primary["windows"]["after 10 sessions"]["unit"] == "task"
    block = primary["blocks"][0]
    assert {c["what"] for c in block["comparisons"]} >= {"H1 fly", "H1 dense", "H4"}
    assert {c["verdict"] for c in block["comparisons"]} <= {"better", "tie", "worse"}
    assert (
        document["secondary_fold_0_reused"]["windows"]["first 10 sessions"]["unit"] == "repository"
    )
    rates = {c["calibrator_rate"] for c in document["chosen_on_validation"]["meta"]}
    cold = {c["calibrator_rate"] for c in document["chosen_on_validation"]["cold"]}
    assert rates == cold  # one rate per filler, shared by cold and meta
