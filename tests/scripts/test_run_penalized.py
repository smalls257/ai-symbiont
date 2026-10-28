"""The penalized-selection runner builds its learners and refuses an unregistered scored run."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "offline"


@pytest.fixture(scope="module")
def script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("run_penalized", SCRIPTS / "run_penalized.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def test_each_registered_learner_is_built_with_its_setting(script):
    assert script.make_learner("counters", 0, None).name == "counters"
    assert script.make_learner("similarity", 0, None).name == "similarity"
    assert script.make_learner("mushroom", 1, None).name == "mushroom"
    dense = script.make_learner("dense", 2, 0.3)
    assert dense.name == "dense" and dense.lr == 0.3


def test_a_dense_learner_without_a_learning_rate_raises(script):
    with pytest.raises(ValueError, match="dense"):
        script.make_learner("dense", 0, None)


def test_scored_without_a_prereg_refuses_before_any_work(script):
    from symbiont.eval.prereg import PreregNotFrozenError

    argv = ["run", "--data", "d", "--meta", "m", "--out", "o", "--scored"]
    with pytest.raises(PreregNotFrozenError, match="--scored needs --prereg"):
        script.main(argv)


def test_scored_with_the_wrong_prereg_refuses(script):
    from symbiont.eval.prereg import PreregNotFrozenError

    root = Path(__file__).resolve().parents[2]
    argv = ["run", "--data", "d", "--meta", "m", "--out", "o", "--scored"]
    argv += ["--prereg", str(root / "prereg" / "2026-10-29-offline-selection.md")]
    with pytest.raises(PreregNotFrozenError):
        script.main(argv)


def test_smoke_and_scored_together_are_refused(script):
    with pytest.raises(SystemExit):
        script.main(
            ["run", "--data", "d", "--meta", "m", "--out", "o", "--scored", "--smoke-train-only"]
        )
