"""Route A warner fit: grouped risks, option A spending and the earn-or-raise threshold rule."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"


@pytest.fixture
def fit(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("warner_fit", ROUTEA / "warner_fit.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "warner_fit", module)
    spec.loader.exec_module(module)
    return module


def steps(fit, labels, boundary, session, fold=None, features=None):
    n = len(labels)
    return fit.Steps(
        features=np.zeros((n, 2)) if features is None else features,
        labels=np.asarray(labels, dtype=bool),
        boundary=np.asarray(boundary, dtype=bool),
        session=np.asarray(session),
        fold=np.zeros(n, dtype=int) if fold is None else np.asarray(fold),
    )


def test_logistic_fit_separates_a_learnable_signal(fit):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 2))
    y = x[:, 0] + 0.3 * rng.normal(size=400) > 0
    model = fit.fit_logistic(x, y, l2=1.0)
    assert fit.auc(y, fit.predict(model, x)) > 0.9
    assert model.coef[1] > 0


def test_one_class_cannot_be_fit(fit):
    with pytest.raises(ValueError, match="both"):
        fit.fit_logistic(np.zeros((3, 1)), np.zeros(3, dtype=bool), 1.0)


def test_out_of_fold_risks_never_see_their_own_fold(fit):
    rng = np.random.default_rng(1)
    x = rng.normal(size=(300, 2))
    y = x[:, 0] > 0
    data = steps(fit, y, [True] * 300, np.arange(300), np.arange(300) % 3, x)
    risks = fit.out_of_fold_risks(data, 1.0)
    assert risks.shape == (300,) and fit.auc(y, risks) > 0.9


def test_option_a_spends_two_notes_per_session_with_a_cooldown(fit):
    data = steps(fit, [True] * 20, [True] * 20, [0] * 14 + [1] * 6)
    spoken = fit.spoken_steps(data, np.ones(20), 0.5)
    assert spoken.tolist() == [0, 6, 14]


def test_only_boundary_steps_at_or_above_the_threshold_speak(fit):
    data = steps(fit, [True] * 4, [False, True, True, True], [0] * 4)
    assert fit.spoken_steps(data, np.array([0.9, 0.9, 0.1, 0.9]), 0.5).tolist() == [1]


def test_sessions_must_be_contiguous(fit):
    with pytest.raises(ValueError, match="contiguous"):
        fit.positions(np.array([0, 1, 0]))


def test_choose_threshold_keeps_the_best_earning_setting(fit):
    labels = [True, False] * 10
    data = steps(fit, labels, [True] * 20, np.arange(20))
    risks = np.where(np.asarray(labels), 0.9, 0.2)
    choice = fit.choose_threshold(data, risks)
    assert choice.note_at > 0.2 and choice.notes == choice.right == 10


def test_choose_threshold_raises_when_no_setting_earns(fit):
    data = steps(fit, [False] * 10, [True] * 10, np.arange(10))
    with pytest.raises(ValueError, match="no threshold earns"):
        fit.choose_threshold(data, np.linspace(0, 1, 10))


def test_auc_counts_ties_half(fit):
    assert fit.auc(np.array([True, False]), np.array([0.5, 0.5])) == 0.5
    assert fit.auc(np.array([True, False, True]), np.array([0.9, 0.1, 0.8])) == 1.0


def test_session_columns_label_trouble_ahead_and_mark_boundaries(monkeypatch, fit):
    from record_builders import run, session

    spec = importlib.util.spec_from_file_location("fit_warner", ROUTEA / "fit_warner.py")
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "fit_warner", script)
    spec.loader.exec_module(script)
    records = session(run("ls", 0), run("pytest tests/t.py", 1, "ImportError: x"), run("ls", 0))
    features, labels, marks = script.session_columns(records)
    assert features.shape == (3, 86)
    assert labels.tolist() == [True, False, False]
    assert marks.tolist() == [False, True, False]


def test_a_held_out_repository_in_the_pool_stops_the_fit(monkeypatch, fit, tmp_path):
    spec = importlib.util.spec_from_file_location("fit_warner", ROUTEA / "fit_warner.py")
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "fit_warner", script)
    spec.loader.exec_module(script)
    (tmp_path / "iterative__dvc.jsonl").write_text("")
    with pytest.raises(ValueError, match="held-out"):
        script.pool_files(tmp_path, None)
