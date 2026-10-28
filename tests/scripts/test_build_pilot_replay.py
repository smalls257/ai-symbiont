"""Pilot trajectories to demo-replay-v1: labels, tags, totals and refusal of unreadable input."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_pilot_replay", ROOT / "scripts" / "routea" / "build_pilot_replay.py"
)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def call(command, at, tokens=(100, 10)):
    usage = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}
    timings = {"prompt_ms": 1000, "predicted_ms": 1000}
    extra = {
        "actions": [{"command": command}],
        "timestamp": at,
        "response": {"usage": usage, "timings": timings},
    }
    return {"role": "assistant", "extra": extra}


def result(at, returncode=0, output=""):
    return {
        "role": "tool",
        "extra": {"timestamp": at, "returncode": returncode, "raw_output": output},
    }


def trajectory(*turns):
    messages = [{"role": "system"}, {"role": "user"}]
    for command, returncode in turns:
        at = len(messages)
        messages += [call(command, at), result(at + 0.5, returncode)]
    return {"messages": messages}


def solved_trajectory():
    traj = trajectory(("ls", 0))
    traj["messages"].append(call("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt", 9))
    traj["messages"].append({"role": "exit"})
    return traj


GRADES = {
    "plain": [
        {"run": 2, "resolved": True, "steps": 2},
        {"run": 3, "resolved": False, "steps": 1},
    ],
    "lesson": [{"run": 1, "resolved": True, "steps": 2}],
}


@pytest.mark.parametrize(
    ("command", "label"),
    [
        ("ls -la", "List the repository root"),
        (
            "python -m unittest tests.dialects.test_duckdb tests.test_parser",
            "Run tests/dialects/test_duckdb.py",
        ),
        ("sed -n '10,20p' sqlglot/parser.py", "Read sqlglot/parser.py lines 10-20"),
        ("sed -i 's/a/b/' sqlglot/dialects/oracle.py", "Edit sqlglot/dialects/oracle.py"),
        ("cat > repro.py << 'EOF'\nprint(1)\nEOF", "Write a scratch script"),
        ("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt", "Submit the patch"),
    ],
)
def test_label_is_public_and_shaped_by_what_the_step_did(command, label):
    assert replay.action_label(command) == label


def tags(*turns):
    steps = replay.steps_from_trajectory(trajectory(*turns), "t", result="not solved")
    return [s["mistake_tag"] for s in steps]


def test_reading_a_different_range_of_a_file_is_not_a_repeat():
    assert tags(("sed -n '10,20p' sqlglot/x.py", 0), ("sed -n '40,60p' sqlglot/x.py", 0)) == [
        "none",
        "none",
    ]


def test_reading_most_of_an_already_read_range_again_is_a_repeat_and_wasted():
    turns = (("sed -n '10,20p' sqlglot/x.py", 0), ("sed -n '12,22p' sqlglot/x.py", 0))
    assert tags(*turns) == ["none", "repeated"]
    steps = replay.steps_from_trajectory(trajectory(*turns), "t", result="not solved")
    assert steps[1]["wasted"] is True


def test_listing_different_directories_is_not_a_repeat_but_the_same_listing_is():
    assert tags(("ls sqlglot", 0), ("ls sqlglot/dialects", 0), ("ls sqlglot", 0)) == [
        "none",
        "none",
        "repeated",
    ]


def test_rerunning_a_command_after_a_source_edit_is_not_a_repeat():
    turns = (
        ("python repro.py", 1),
        ("sed -i 's/a/b/' sqlglot/x.py", 0),
        ("python repro.py", 0),
    )
    assert tags(*turns) == ["new", "none", "none"]


def test_first_failure_is_new_and_the_same_failure_again_is_repeated():
    steps = replay.steps_from_trajectory(
        trajectory(("python x.py", 1), ("python x.py", 1)), "t", result="not solved"
    )
    assert [s["mistake_tag"] for s in steps] == ["new", "repeated"]
    assert [s["outcome"] for s in steps] == ["failed", "failed"]


def test_submit_step_of_a_resolved_run_is_solved_and_has_no_tool_result():
    traj = trajectory(("ls", 0))
    traj["messages"].append(call("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt", 9))
    traj["messages"].append({"role": "exit"})
    steps = replay.steps_from_trajectory(traj, "t", result="solved")
    assert steps[-1]["outcome"] == "solved"
    assert steps[0]["wall_s"] == 2.5  # model 2.0 s plus tool 0.5 s


def test_missing_usage_raises_naming_the_step():
    traj = trajectory(("ls", 0))
    del traj["messages"][2]["extra"]["response"]["usage"]
    with pytest.raises(replay.TrajectoryError, match="t step 1"):
        replay.steps_from_trajectory(traj, "t", result="not solved")


def test_totals_are_the_sums_of_the_steps():
    steps = replay.steps_from_trajectory(
        trajectory(("ls", 0), ("python x.py", 1)), "t", result="not solved"
    )
    totals = replay.totals_of(steps, result="not solved")
    assert totals["tokens_in"] == 200
    assert totals["wall_s"] == pytest.approx(5.0)
    assert (totals["new_mistakes"], totals["result"]) == (1, "not solved")


def test_replay_gives_the_lesson_note_only_to_the_lesson_run_and_labels_it_honestly():
    pair = replay.PAIRS[0]
    doc = replay.build_replay(pair, trajectory(("ls", 0)), solved_trajectory(), GRADES)
    plain, lesson = doc["runs"]
    assert plain["steps"][0]["note"] is None and plain["adapter"] is None
    assert lesson["steps"][0]["note"]["source"] == "lesson in prompt (pilot)"
    assert doc["status"] == "measured" and "not the LoRA" in doc["source"]
    assert json.dumps(doc) and all(s["classifier"] is None for r in doc["runs"] for s in r["steps"])


def test_note_fields_stay_within_twelve_words():
    for pair in replay.PAIRS:
        assert all(len(text.split()) <= 12 for text in pair.note.values())


def test_each_run_carries_its_own_subtitle():
    doc = replay.build_replay(replay.PAIRS[0], trajectory(("ls", 0)), solved_trajectory(), GRADES)
    plain, lesson = doc["runs"]
    assert plain["subtitle"] == "Glimmer, no adapter, no notes"
    assert "lesson in the prompt" in lesson["subtitle"] and "no adapter" in lesson["subtitle"]


def test_replay_states_the_arms_full_record_and_which_run_is_shown():
    doc = replay.build_replay(replay.PAIRS[0], trajectory(("ls", 0)), solved_trajectory(), GRADES)
    plain, lesson = doc["runs"]
    assert (plain["shown_run"], plain["runs_solved"], plain["runs_total"]) == (3, 1, 2)
    assert (lesson["shown_run"], lesson["runs_solved"], lesson["runs_total"]) == (1, 1, 1)


def test_result_comes_from_the_grader_and_a_disagreeing_trajectory_raises():
    grades = {**GRADES, "plain": [{"run": 3, "resolved": True, "steps": 1}]}
    with pytest.raises(replay.TrajectoryError, match="grader"):
        replay.build_replay(replay.PAIRS[0], trajectory(("ls", 0)), solved_trajectory(), grades)


def test_a_step_count_the_grader_does_not_share_raises():
    grades = {**GRADES, "plain": [{"run": 3, "resolved": False, "steps": 7}]}
    with pytest.raises(replay.TrajectoryError, match="7"):
        replay.build_replay(replay.PAIRS[0], trajectory(("ls", 0)), solved_trajectory(), grades)


def test_rewriting_a_scratch_script_and_rerunning_it_is_not_a_repeat():
    turns = (
        ("cat > /tmp/try.py << 'EOF'\nprint(1)\nEOF", 0),
        ("python /tmp/try.py", 0),
        ("cat > /tmp/try.py << 'EOF'\nprint(2)\nEOF", 0),
        ("python /tmp/try.py", 0),
    )
    assert tags(*turns) == ["none", "none", "none", "none"]


def test_rerunning_a_script_that_was_not_rewritten_is_a_repeat():
    assert tags(("python /tmp/try.py", 0), ("python /tmp/try.py", 0)) == ["none", "repeated"]


def test_a_python_heredoc_that_writes_a_file_also_resets_its_commands():
    write = "python3 - << 'PY'\nopen('/tmp/try.py', 'w').write('x')\nPY"
    assert tags(("python /tmp/try.py", 1), (write, 0), ("python /tmp/try.py", 0)) == [
        "new",
        "none",
        "none",
    ]
