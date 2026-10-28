"""The lesson-set builder: synthetic episodes on disk in, Route B layout and counts out."""

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from symbiont.act1.episode import Decision, build_prompt
from symbiont.act1.episode_records import PROVENANCE
from symbiont.records.schema import Kind, Record, dump_jsonl

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "act1" / "build_lesson_set.py"
SESSION = "MAP03-random-s1"


def load_script():
    spec = importlib.util.spec_from_file_location("build_lesson_set_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record(index, move, outcome, rooms, pains=()):
    facts = {
        "level": "MAP03",
        "decision": index,
        "outcome": outcome,
        "room_before": rooms[0],
        "room_after": rooms[1],
        "angle": 0,
        "keys_held": [],
        "ended": None,
    }
    return Record(
        harness="vizdoom",
        project="freedoom2",
        session_id=SESSION,
        step=index,
        kind=Kind.COMMAND,
        raw=json.dumps(facts),
        provenance=PROVENANCE,
        command=f"scripted {move}",
        tags=tuple(f"pain:{pain}" for pain in pains),
    )


def decision(index, reply, outcome, status="ok"):
    return Decision(index, f"view {index}", reply, status, None, "stop", 0, (outcome,), 0.0)


def write_episode(episodes, *, with_log=True, failed_run_first=False):
    level = episodes / "MAP03"
    level.mkdir(parents=True)
    records = [
        record(0, "open_door()", "no door in reach", (1, 1), ["wasted_move"]),
        record(1, "open_door()", "no door in reach", (1, 1), ["wasted_move"]),
        record(2, "go_to(door)", "arrived at door", (1, 2)),
    ]
    with (level / f"{SESSION}.jsonl").open("w") as handle:
        dump_jsonl(records, handle)
    if not with_log:
        return
    played = [
        decision(0, "open_door()", "scripted open_door() -> no door in reach"),
        decision(1, "open_door()", "scripted open_door() -> no door in reach"),
        decision(2, "go_to(door)", "scripted go_to(door) -> arrived at door"),
    ]
    runs = ([[decision(0, "turn(9", "x", status="invalid")]] if failed_run_first else []) + [played]
    lines = []
    for run in runs:
        lines.append(json.dumps({"run_header": {"session_id": SESSION}}))
        lines += [json.dumps(asdict(d)) for d in run]
    (level / f"{SESSION}.decisions.jsonl").write_text("\n".join(lines) + "\n")


def build(module, tmp_path, *extra):
    module.main(
        ["--episodes", str(tmp_path / "ep"), "--work", str(tmp_path / "w"), "--min-lessons", "1"]
        + list(extra)
    )
    data = tmp_path / "w" / "data"
    rows = [json.loads(line) for line in (data / "train" / "freedoom" / "train.jsonl").open()]
    return rows, json.loads((data / "build-counts.json").read_text())


def test_episodes_become_lessons_rows_and_counts(tmp_path, capsys):
    write_episode(tmp_path / "ep", failed_run_first=True)
    rows, counts = build(load_script(), tmp_path)
    assert counts["lessons_selected"] == 1 and counts["repeated_selected"] == 1
    assert counts["training_rows"] == 3 and counts["situation_rows"] == 1
    assert counts["mistakes"] == {"wasted_move": 2}
    situation = rows[2]["messages"]
    history = [
        "scripted open_door() -> no door in reach",
        "scripted open_door() -> no door in reach",
    ]
    assert situation[1]["content"] == build_prompt("view 2", history)
    assert situation[2]["content"] == "go_to(door)"
    assert counts["user_chars_max"] == len(situation[1]["content"])
    assert "no door in reach" not in capsys.readouterr().out  # counts only, never lesson text


def test_records_without_a_decision_log_stop_the_build(tmp_path):
    write_episode(tmp_path / "ep", with_log=False)
    with pytest.raises(FileNotFoundError, match="no decision log"):
        build(load_script(), tmp_path)


def test_too_few_lessons_stop_the_build(tmp_path):
    write_episode(tmp_path / "ep")
    with pytest.raises(ValueError, match="needs 5"):
        build(load_script(), tmp_path, "--min-lessons", "5")
