"""One night with fake tools: stages in order, the record only after a trainer that exited 0.

Violation prevented: Silent Fallback. A failed trainer, a missing store or no lessons each end the
night loudly and non-zero, and none of them replaces the older adapter or record.
"""

import json
from pathlib import Path

import pytest

from nightly_support import (
    PROJECT,
    FakeNight,
    failed_command_lesson,
    general_rows,
    habit_rows,
)
from symbiont.miner.twins import merge_twins
from symbiont.service.nightly import NightlyJudges, NightlyState, lessons_digest
from symbiont.service.nightly_backend import Backend
from symbiont.service.nightly_run import (
    EXIT_FAILED,
    EXIT_NO_LESSONS,
    NightPlan,
    run_night,
)
from symbiont.store.local import Source, Store

pytestmark = pytest.mark.periphery
URL = "http://127.0.0.1:8861"


def write_kit(root):
    (root / "base").mkdir(parents=True)
    (root / "base" / "config.json").write_text("{}")
    for name, rows in (("general-rows.jsonl", general_rows(60)), ("habits.jsonl", habit_rows(8))):
        (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))


def setup(tmp_path, lessons=6):
    data = tmp_path / "data"
    data.mkdir()
    store = Store.open(data / "store.db")
    store.save_mining(
        PROJECT,
        [Source(PROJECT, "claude_code", "x")],
        [failed_command_lesson(i) for i in range(lessons)],
        held_out_tasks=frozenset(),
    )
    write_kit(tmp_path / "kit")
    return NightPlan(PROJECT, data, data / "nightly", tmp_path / "kit", URL, "py")


def test_a_night_trains_installs_the_adapter_records_it_and_tells_the_judge(tmp_path):
    plan = setup(tmp_path)
    night = FakeNight(Backend.MLX)
    assert run_night(plan, night.tools()) == 0
    adapter = plan.nightly_dir / PROJECT / "adapter"
    assert sorted(p.name for p in adapter.iterdir()) == [
        "adapter_config.json",
        "adapter_model.safetensors",
    ]
    record = json.loads((plan.nightly_dir / PROJECT / "nightly.json").read_text())
    assert (record["lesson_count"], record["backend"], record["judge_url"]) == (6, "mlx", URL)
    assert record["trained_at"] == "2026-11-03T03:00:00+00:00"
    assert record["judge_start"] == {
        "python": "python3",
        "base": str(plan.kit_dir / "base"),
        "adapter": str(adapter),
        "device": "mps",
        "port": 8861,
    }
    assert night.judge_calls == [(URL, adapter, plan.kit_dir / "base")]
    assert any("trained on 6 lessons" in line for line in night.said)


def test_the_record_matches_the_stores_lessons_so_status_reads_trained_then_stale(tmp_path):
    plan = setup(tmp_path)
    run_night(plan, FakeNight(Backend.MLX).tools())
    store = Store.open(plan.data_dir / "store.db")
    judges = NightlyJudges(plan.nightly_dir)
    report = judges.report(PROJECT, store.lessons(PROJECT))
    assert (report.state, report.lessons) == (NightlyState.TRAINED, 6)
    store.save_mining(
        PROJECT, [Source(PROJECT, "claude_code", "x")],
        [failed_command_lesson(i) for i in range(7)], held_out_tasks=frozenset(),
    )  # fmt: skip
    assert judges.report(PROJECT, store.lessons(PROJECT)).state is NightlyState.STALE


def test_every_stage_prints_its_seconds_and_the_lesson_count(tmp_path):
    night = FakeNight(Backend.MLX)
    run_night(setup(tmp_path), night.tools())
    text = "\n".join(night.said)
    for stage in ("read lessons", "build rows", "train", "install adapter", "write record"):
        assert f"  {stage}: " in text
    assert "6 lessons; training on mlx" in text


def test_mlx_trains_fresh_from_the_kits_base_on_rows_with_the_recipe_mix(tmp_path):
    plan = setup(tmp_path)
    night = FakeNight(Backend.MLX)
    run_night(plan, night.tools())
    (command,) = night.commands
    assert command[command.index("--model") + 1] == str(plan.kit_dir / "base")
    assert "--resume-adapter-file" not in command
    rows = (plan.nightly_dir / PROJECT / "work" / "data" / "train.jsonl").read_text().splitlines()
    assert sum('"habit"' in row for row in rows) / len(rows) == pytest.approx(0.15, abs=0.02)
    assert (plan.nightly_dir / PROJECT / "work" / "lora.yaml").is_file()


def test_cuda_runs_the_torch_trainer_with_the_cuda_device(tmp_path):
    night = FakeNight(Backend.TORCH_CUDA)
    assert run_night(setup(tmp_path), night.tools()) == 0
    assert night.commands[0][1] == str(Path("/scripts/train_lora_torch.py"))
    assert night.environments[0]["LCAP_DEVICE"] == "cuda"


def test_a_failed_trainer_exits_nonzero_keeps_the_old_adapter_and_writes_no_record(tmp_path):
    plan = setup(tmp_path)
    old = plan.nightly_dir / PROJECT / "adapter"
    old.mkdir(parents=True)
    (old / "adapter_model.safetensors").write_bytes(b"yesterday")
    night = FakeNight(Backend.MLX, exit_code=7)
    assert run_night(plan, night.tools()) == EXIT_FAILED
    assert (old / "adapter_model.safetensors").read_bytes() == b"yesterday"
    assert not (plan.nightly_dir / PROJECT / "nightly.json").exists()
    assert any("exited 7" in line and "train.log" in line for line in night.said)
    assert night.judge_calls == []


def test_a_trainer_that_exits_zero_but_writes_no_adapter_is_a_failure(tmp_path):
    plan = setup(tmp_path)
    night = FakeNight(Backend.MLX, trainer_writes=False)
    assert run_night(plan, night.tools()) == EXIT_FAILED
    assert not (plan.nightly_dir / PROJECT / "nightly.json").exists()


def test_a_failed_night_leaves_the_older_record_which_then_reads_as_stale(tmp_path):
    plan = setup(tmp_path, lessons=4)
    run_night(plan, FakeNight(Backend.MLX).tools())
    store = Store.open(plan.data_dir / "store.db")
    store.save_mining(
        PROJECT, [Source(PROJECT, "claude_code", "x")],
        [failed_command_lesson(i) for i in range(5)], held_out_tasks=frozenset(),
    )  # fmt: skip
    assert run_night(plan, FakeNight(Backend.MLX, exit_code=1).tools()) == EXIT_FAILED
    report = NightlyJudges(plan.nightly_dir).report(PROJECT, store.lessons(PROJECT))
    assert (report.state, report.lessons) == (NightlyState.STALE, 4)


def test_no_lessons_says_so_and_exits_with_its_own_code(tmp_path):
    plan = setup(tmp_path)
    night = FakeNight(Backend.MLX)
    empty = NightPlan("nobody", plan.data_dir, plan.nightly_dir, plan.kit_dir, URL, "py")
    assert run_night(empty, night.tools()) == EXIT_NO_LESSONS
    assert any("no stored lessons" in line for line in night.said)
    assert night.commands == []


def test_a_missing_store_is_a_named_failure_not_an_empty_night(tmp_path):
    plan = setup(tmp_path)
    missing = NightPlan(PROJECT, tmp_path / "elsewhere", tmp_path / "n", plan.kit_dir, URL, "py")
    night = FakeNight(Backend.MLX)
    assert run_night(missing, night.tools()) == EXIT_NO_LESSONS
    assert any("no symbiont data" in line for line in night.said)


def test_lessons_without_a_fix_command_fail_loudly_instead_of_training_on_nothing(tmp_path):
    plan = setup(tmp_path, lessons=0)
    store = Store.open(plan.data_dir / "store.db")
    lesson = failed_command_lesson(1)
    unfit = type(lesson)(lesson.pain_point, lesson.quote, (), "no fix", True, lesson.sources)
    store.save_mining(
        PROJECT, [Source(PROJECT, "claude_code", "x")], [unfit], held_out_tasks=frozenset()
    )
    night = FakeNight(Backend.MLX)
    assert run_night(plan, night.tools()) == EXIT_FAILED
    assert any("failed command and a fix" in line for line in night.said)


def test_the_digest_in_the_record_is_the_one_the_service_computes(tmp_path):
    plan = setup(tmp_path)
    run_night(plan, FakeNight(Backend.MLX).tools())
    record = json.loads((plan.nightly_dir / PROJECT / "nightly.json").read_text())
    stored = merge_twins(Store.open(plan.data_dir / "store.db").lessons(PROJECT))
    assert record["lessons_digest"] == lessons_digest(stored)


def test_a_missing_kit_is_reported_before_the_lessons_are_read(tmp_path):
    setup(tmp_path)
    # the data dir has no store: reading lessons first would say "no symbiont data" instead
    bare = NightPlan(PROJECT, tmp_path / "elsewhere", tmp_path / "n", tmp_path / "nokit", URL, "py")
    night = FakeNight(Backend.MLX)
    assert run_night(bare, night.tools()) == EXIT_FAILED
    assert any("judge kit" in line and "symbiont nightly setup" in line for line in night.said)
    assert not any("no symbiont data" in line for line in night.said)
    assert night.commands == []
