"""The CUDA LCAP trainer follows the laptop's mlx-lm recipe: lr curve, batch order, loss span.

The expected numbers were read from mlx-lm 0.32.2 itself (build_schedule, iterate_batches,
default_loss) on the laptop; these tests pin them so the CUDA port cannot drift silently.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"


@pytest.fixture
def recipe(monkeypatch):
    spec = importlib.util.spec_from_file_location("mlx_lora_recipe", ROUTEA / "mlx_lora_recipe.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "mlx_lora_recipe", module)
    spec.loader.exec_module(module)
    return module


def test_the_lr_warms_up_for_twenty_updates_then_decays_by_cosine(recipe):
    assert recipe.learning_rate(0, 120) == pytest.approx(1e-6)
    assert recipe.learning_rate(10, 120) == pytest.approx(5.05e-5)
    # mlx-lm joins the schedules at warmup + 1, so updates 20 and 21 both sit at the peak
    assert recipe.learning_rate(20, 120) == pytest.approx(1e-4)
    assert recipe.learning_rate(21, 120) == pytest.approx(1e-4)
    # cosine_decay over `iters` steps that start after the join, so it never reaches 1e-6;
    # the 120-iter run ends near 9e-6, the 1,200-iter run near 1.08e-6 (mlx-lm's own numbers)
    assert recipe.learning_rate(119, 120) == pytest.approx(8.9858e-6, rel=1e-4)
    assert recipe.learning_rate(1199, 1200) == pytest.approx(1.0821e-6, rel=1e-4)


def test_batches_are_length_sorted_whole_and_each_visited_once_per_pass(recipe):
    lengths = [50, 10, 40, 20, 30, 60, 70, 80, 5]  # 9 rows: the longest is the dropped tail
    order = recipe.batch_order(lengths, 4, 4, seed=0)
    # by length the rows run 8 1 3 4 | 2 0 5 6 | 7, and row 7 alone is a tail, never trained
    batches = [[2, 0, 5, 6], [8, 1, 3, 4]]
    assert sorted(order[:2]) == batches  # first pass: every batch once
    assert sorted(order[2:]) == batches  # second pass: every batch once again
    assert order == recipe.batch_order(lengths, 4, 4, seed=0)


def test_too_few_rows_for_one_batch_raise(recipe):
    with pytest.raises(ValueError, match="cannot fill one batch"):
        recipe.batch_order([3, 4, 5], 4, 10, seed=0)


def test_the_batch_width_pads_to_one_plus_a_multiple_of_32_capped_at_512(recipe):
    assert recipe.padded_width([31, 12]) == 33
    assert recipe.padded_width([33]) == 65
    assert recipe.padded_width([600]) == 512


def test_loss_covers_the_completion_and_the_one_pad_target_after_it(recipe):
    # tokens 0..9 with the reply starting at token 6, in an array 13 wide (12 targets)
    span = recipe.loss_span(offset=6, length=10, width=13)
    targets_predicted = [t + 1 for t in span]  # target t predicts token t + 1
    assert targets_predicted == [6, 7, 8, 9, 10]  # 6..9 are the reply, 10 is the first pad
    assert recipe.loss_span(offset=6, length=13, width=13) == range(5, 12)
