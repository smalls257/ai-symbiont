"""The general-pilot launcher refuses to start without the serving check or its inputs."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibration" / "launch_general_pilot.sh"


def launch(tmp_path, env):
    return subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path)],
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_refuses_without_the_serving_check(tmp_path):
    found = launch(tmp_path, {"SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1"})
    assert found.returncode != 0
    assert "GENERAL_PILOT_SERVING_OK" in found.stderr


def test_refuses_when_an_input_is_missing(tmp_path):
    env = {"SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1", "GENERAL_PILOT_SERVING_OK": "2026-10-28"}
    found = launch(tmp_path, env)
    assert found.returncode == 66
    assert "missing" in found.stderr


def test_refuses_a_task_list_that_is_not_the_split(tmp_path):
    for path in ("calibration-v2/launch.py", ".venv/bin/activate"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    pilot = tmp_path / "runs-general-pilot"
    pilot.mkdir()
    (pilot / "eval-tasks.jsonl").write_text('{"instance_id": "a"}\n')
    (pilot / "general-card.json").write_text("{}")
    env = {"SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1", "GENERAL_PILOT_SERVING_OK": "2026-10-28"}
    found = launch(tmp_path, env)
    assert found.returncode == 66
    assert "expected 18" in found.stderr


def test_scorer_counts_per_arm_and_kind_and_refuses_strays(tmp_path):
    import importlib.util
    import json

    import pytest

    path = SCRIPT.parents[1] / "routeb" / "score_general_pilot.py"
    spec = importlib.util.spec_from_file_location("score_general_pilot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    split = {"evaluation": [{"task": "a", "kind": "bug"}, {"task": "b", "kind": "feature"}]}
    plain, card = tmp_path / "plain.jsonl", tmp_path / "card.jsonl"
    plain.write_text(
        json.dumps({"instance_id": "a", "arm": "plain", "resolved": False, "submitted": False})
        + "\n"
    )
    card.write_text(
        "\n".join(
            json.dumps({"instance_id": t, "arm": "lesson", "resolved": t == "b", "submitted": True})
            for t in ("a", "b")
        )
    )
    found = module.score(split, {"plain": plain, "card": card})
    assert found["arms"]["card"]["feature"] == {"runs": 1, "solved": 1, "submitted": 1}
    assert found["arms"]["plain"]["all"]["solved"] == 0
    card.write_text(json.dumps({"instance_id": "zz", "arm": "lesson", "resolved": True}))
    with pytest.raises(ValueError, match="zz"):
        module.score(split, {"plain": plain, "card": card})
