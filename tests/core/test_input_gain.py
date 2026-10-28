import numpy as np
import pytest

from symbiont.core.input_gain import fit_input_gain


def test_gain_centers_and_scales_each_input():
    rows = np.array([[0.0, 1.0, 7.0], [0.0, 0.0, 5.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]])
    normalized = fit_input_gain(rows).apply(rows)
    assert np.allclose(normalized[:, 1:].mean(axis=0), 0.0)
    assert np.allclose(normalized[:, 1:].std(axis=0), 1.0)


def test_an_input_that_never_varied_stays_finite():
    rows = np.array([[0.0, 2.0], [0.0, 4.0]])
    normalized = fit_input_gain(rows).apply(np.array([3.0, 3.0]))
    assert np.all(np.isfinite(normalized)) and normalized[0] == 3.0


def test_gain_is_fixed_after_fitting():
    gain = fit_input_gain(np.array([[1.0], [3.0]]))
    assert gain.apply(np.array([[2.0]]))[0, 0] == 0.0
    assert gain.apply(np.array([[100.0]]))[0, 0] == pytest.approx(98.0)


def test_fitting_on_nothing_raises():
    with pytest.raises(ValueError, match="non-empty"):
        fit_input_gain(np.zeros((0, 3)))
