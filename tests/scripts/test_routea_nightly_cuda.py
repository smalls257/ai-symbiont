"""The CUDA nightly update follows the laptop's per-repo recipe: warmup, budget, row mix.

Expected numbers come from the MLX run's own logs (a3-acorg__dark-matter: 90 rows, 8 epochs,
180 iters; a3_replay: 120 rows, 240 iters) and from mlx-lm's schedule join; hand-written rows only.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}


@pytest.fixture(autouse=True)
def forget_script_modules():
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


def load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    monkeypatch.syspath_prepend(str(ROUTEA.parent / "aidev"))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recipe(monkeypatch):
    return load(monkeypatch, "mlx_lora_recipe")


@pytest.fixture
def scale(monkeypatch):
    return load(monkeypatch, "nightly_scale")


def test_short_runs_warm_up_for_a_fifth_of_their_updates_longer_ones_for_twenty(recipe):
    # train_lora.sh: warmup=$(( iters < 100 ? iters / 5 : 20 ))
    assert recipe.warmup_for(60) == 12
    assert recipe.warmup_for(99) == 19
    assert recipe.warmup_for(100) == 20
    assert recipe.warmup_for(1200) == 20


def test_a_shorter_warmup_moves_the_peak_and_the_join(recipe):
    # 60 iters, warmup 12: linear for 12 updates, joined at 13, peak held on both sides of it
    assert recipe.learning_rate(6, 60, warmup=12) == pytest.approx(5.05e-5)
    assert recipe.learning_rate(12, 60, warmup=12) == pytest.approx(1e-4)
    assert recipe.learning_rate(13, 60, warmup=12) == pytest.approx(1e-4)
    assert recipe.learning_rate(59, 60, warmup=12) < 2.5e-5


def test_the_default_warmup_is_the_lcap_one(recipe):
    assert recipe.learning_rate(10, 120) == recipe.learning_rate(10, 120, warmup=20)


def test_a_pass_budget_is_rows_times_epochs_over_the_batch(recipe):
    assert recipe.epoch_iters(rows=90, epochs=8, batch=4) == 180
    assert recipe.epoch_iters(rows=120, epochs=8, batch=4) == 240
    assert recipe.epoch_iters(rows=1373, epochs=1, batch=4) == 343


def test_too_few_rows_for_one_update_is_an_error_not_a_zero_run(recipe):
    with pytest.raises(ValueError, match="too few rows"):
        recipe.epoch_iters(rows=3, epochs=1, batch=4)


def row(tag):
    return {"messages": [{"role": "user", "content": tag}]}


def test_habit_rows_are_what_replay_added_to_the_plain_mix(scale):
    plain = [row("a"), row("b"), row("a")]
    replay = [row("h1"), row("a"), row("b"), row("h2"), row("a")]
    assert scale.habit_rows_from(replay, plain) == [row("h1"), row("h2")]


def test_lesson_rows_come_six_to_a_lesson_from_repos_in_name_order(scale):
    pool = {"b/repo": [row(f"b{i}") for i in range(12)], "a/repo": [row(f"a{i}") for i in range(6)]}
    rows = scale.own_rows_for(3, pool)  # three lessons: 18 rows
    assert rows[:6] == [row(f"a{i}") for i in range(6)]
    assert rows[6:] == [row(f"b{i}") for i in range(12)]


def test_a_pool_too_small_for_the_lesson_count_raises(scale):
    with pytest.raises(ValueError, match="needs 150 rows"):
        scale.own_rows_for(25, {"a/repo": [row("x")] * 30})


def test_the_nightly_mix_is_own_plus_two_reading_per_own_plus_one_habit_per_own(scale):
    own = [row(f"o{i}") for i in range(6)]
    reading = [row(f"r{i}") for i in range(40)]
    habits = [row(f"h{i}") for i in range(40)]
    mixed = scale.nightly_rows(own, reading, habits)
    assert len(mixed) == 6 * (1 + 2 + 1)
    assert all(r in mixed for r in own)
    assert scale.nightly_rows(own, reading, habits) == mixed  # fixed seed: same rows every night


def test_a_small_habit_pool_repeats_to_cover_a_big_night(scale):
    pool = [row("h0"), row("h1")]
    assert scale.tiled(pool, 5) == [row("h0"), row("h1"), row("h0"), row("h1"), row("h0")]
    assert scale.tiled(pool, 2) == pool
    with pytest.raises(ValueError, match="no habit rows"):
        scale.tiled([], 3)


def test_the_check_sentences_cover_the_five_kinds(monkeypatch):
    checks = load(monkeypatch, "habit_checks").checks()
    assert len(checks) == 5
    assert all(isinstance(text, str) and text for text in checks.values())


def test_scale_files_hold_the_rows_of_each_lesson_count(scale, tmp_path):
    def write(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    reading = [
        {"messages": [{"role": "system", "content": f"What you remember: {i}"}]} for i in range(200)
    ]
    habit = [row(f"h{i}") for i in range(4)]
    for name in ("a/one", "b/two", "c/three"):
        own = [row(f"{name}{i}") for i in range(30)]
        write(tmp_path / "repos" / name.replace("/", "__") / "per_repo" / "train.jsonl", own)
        write(tmp_path / "repos" / name.replace("/", "__") / "a3" / "train.jsonl", own)
        write(
            tmp_path / "repos" / name.replace("/", "__") / "a3_replay" / "train.jsonl", own + habit
        )
    write(tmp_path / "meta" / "train.jsonl", reading)
    counts = scale.write_scales(tmp_path, [5, 10])
    assert counts == {5: 30 * 4, 10: 60 * 4}
    lines = (tmp_path / "scale" / "10" / "train.jsonl").read_text().splitlines()
    assert len(lines) == 240
