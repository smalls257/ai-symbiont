"""Personal Glimmer (LoRA) replays: honest labels, record line, refusal of dishonest pairs."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "routea"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import sys  # noqa: E402  (the sibling import path must exist before the emitter loads)

sys.path.insert(0, str(SCRIPTS))
emitter = _load("build_personal_replay")


def call(command, at):
    extra = {
        "actions": [{"command": command}],
        "timestamp": at,
        "response": {
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            "timings": {"prompt_ms": 1000, "predicted_ms": 1000},
        },
    }
    return {"role": "assistant", "extra": extra}


def failed_run():
    messages = [{"role": "system"}, {"role": "user"}, call("ls", 1)]
    messages.append(
        {"role": "tool", "extra": {"timestamp": 1.5, "returncode": 0, "raw_output": ""}}
    )
    return {"messages": messages}


def solved_run():
    run = failed_run()
    run["messages"].append(call("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt", 9))
    run["messages"].append({"role": "exit"})
    return run


def plain_row(run, *, resolved, steps=1):
    return {
        "instance_id": "tobymao__sqlglot-1379",
        "stage": "confirm",
        "run": run,
        "resolved": resolved,
        "steps": steps,
        "adapter_id": None,
    }


def personal_row(**over):
    row = {
        "instance_id": "tobymao__sqlglot-1379",
        "stage": "cal2",
        "run": 1,
        "resolved": True,
        "steps": 2,
        "adapter_id": 0,
        "arm": "personal_lora",
        "lesson_sha": None,
    }
    return {**row, **over}


PLAIN = [plain_row(2, resolved=True, steps=2), plain_row(3, resolved=False)]


def build(plain=PLAIN, personal=None):
    personal = personal or [personal_row()]
    return emitter.build_replay("1379", failed_run(), solved_run(), plain, personal)


def test_labels_say_adapter_and_no_lesson_and_the_plain_run_has_no_adapter():
    plain, personal = build()["runs"]
    assert personal["label"] == "Personal Glimmer (LoRA adapter, sqlglot)"
    assert "no lesson in the prompt" in personal["subtitle"]
    assert personal["adapter"] and plain["adapter"] is None
    assert (plain["role"], personal["role"]) == ("floor", "under test")


def test_no_run_carries_a_note_a_classifier_or_a_picker():
    for run in build()["runs"]:
        assert all(
            s["note"] is None and s["classifier"] is None and s["picker"] is None
            for s in run["steps"]
        )


def test_the_page_record_names_the_failed_plain_run_and_the_full_arm_record():
    plain, personal = build()["runs"]
    assert (plain["shown_run"], plain["runs_solved"], plain["runs_total"]) == (3, 1, 2)
    assert (personal["shown_run"], personal["runs_solved"], personal["runs_total"]) == (1, 1, 1)
    assert (plain["totals"]["result"], personal["totals"]["result"]) == ("not solved", "solved")


def test_an_unsolved_personal_run_raises_rather_than_being_shown():
    with pytest.raises(emitter.TrajectoryError, match="did not solve"):
        build(personal=[personal_row(resolved=False)])


def test_a_plain_arm_with_no_failure_raises():
    with pytest.raises(emitter.TrajectoryError, match="no failed plain run"):
        build(plain=[plain_row(2, resolved=True, steps=2)])


def test_a_row_without_the_adapter_or_with_a_lesson_is_refused(tmp_path):
    path = tmp_path / "personal-rows.jsonl"
    for bad in ({"adapter_id": None}, {"lesson_sha": "abc"}, {"arm": "lesson"}):
        path.write_text(json.dumps(personal_row(**bad)) + "\n")
        with pytest.raises(emitter.TrajectoryError):
            emitter.personal_rows(path, "1379")


def test_a_trajectory_the_grader_disagrees_with_raises():
    with pytest.raises(emitter.TrajectoryError, match="grader"):
        build(personal=[personal_row(steps=5)])


def test_write_replay_reads_the_staged_files(tmp_path):
    (tmp_path / "1379-plain.json").write_text(json.dumps(failed_run()))
    (tmp_path / "1379-personal.json").write_text(json.dumps(solved_run()))
    (tmp_path / "plain-rows.jsonl").write_text("\n".join(json.dumps(r) for r in PLAIN) + "\n")
    (tmp_path / "personal-rows.jsonl").write_text(json.dumps(personal_row()) + "\n")
    out = emitter.write_replay(tmp_path, tmp_path, "1379")
    assert json.loads(out.read_text())["task"]["id"] == "sqlglot-1379"


def test_the_shown_personal_run_is_the_lowest_numbered_solved_row():
    rows = [
        personal_row(run=3, steps=2),
        personal_row(run=2, steps=2),
        personal_row(run=1, resolved=False, steps=2),
    ]
    assert build(personal=rows)["runs"][1]["shown_run"] == 2


def test_arm_totals_line_counts_the_whole_eval_and_says_exploratory():
    other = {**personal_row(instance_id="tobymao__sqlglot-9"), "resolved": False}
    plain_other = {**plain_row(2, resolved=False), "instance_id": "tobymao__sqlglot-9"}
    line = emitter.arm_totals_line(PLAIN + [plain_other], [personal_row(), other])
    assert "Exploratory, n = 1 per task" in line
    assert "personal Glimmer solved 1 of 2 runs" in line
    assert "plain Glimmer solved 1 of 3 confirm runs" in line
