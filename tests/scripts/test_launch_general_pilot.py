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


OVERNIGHT = SCRIPT.parent / "overnight_general_eval.sh"


def _overnight_work(tmp_path):
    for path in ("calibration-general/launch.py", ".venv/bin/activate"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    out = tmp_path / "runs-general-overnight"
    out.mkdir()
    (out / "eval-tasks.jsonl").write_text('{"instance_id": "a"}\n')
    (out / "general-split.json").write_text('{"evaluation": [{"task": "a", "kind": "bug"}]}')
    return out


def test_overnight_waiter_gives_up_at_the_deadline_and_writes_a_summary(tmp_path):
    import time

    out = _overnight_work(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text("#!/bin/sh\nexit 7\n")  # Glimmer unreachable all night
    (fake_bin / "curl").chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1/v1",
        "POLL_S": "1",
        "DEADLINE": str(int(time.time()) + 2),
        "QUEUE_SUMMARY": str(tmp_path / "none.txt"),
    }
    found = subprocess.run(
        ["bash", str(OVERNIGHT), str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert found.returncode == 0, found.stderr
    log = (out / "overnight.log").read_text()
    assert "never served: Muse-Glimmer-30B-sqlglot-general Muse-Glimmer-30B-sqlglot-habits" in log
    assert "plain (reference, pilot): not run" in (out / "summary.txt").read_text()


def test_overnight_waiter_starts_only_adapters_the_queue_installed(tmp_path):
    import time

    out = _overnight_work(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ids = ("Muse-Glimmer-30B-sqlglot-general", "Muse-Glimmer-30B-sqlglot-habits")
    models = '{"data":[' + ",".join(f'{{"id":"{name}"}}' for name in ids) + "]}"
    (fake_bin / "curl").write_text(
        '#!/bin/sh\ncase "$*" in *health*) echo \'{"status":"ok"}\';;'
        f" *) echo '{models}';; esac\n"
    )
    (fake_bin / "curl").chmod(0o755)
    queue = tmp_path / "queue.txt"
    queue.write_text(
        "general install a b ok model=Muse-Glimmer-30B-sqlglot-general\n"
        "habits install a b FAILED rolled-back model=Muse-Glimmer-30B-sqlglot-habits\n"
        "end check a llama=true\n"
    )
    (out / "arm-labels.json").write_text('{"sqlglot-general-rerun": "under test, rerun"}')
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1/v1",
        "POLL_S": "1",
        "DEADLINE": str(int(time.time()) + 4),
        "QUEUE_SUMMARY": str(queue),
        "ARM_SUFFIX": "-rerun",
        "PLAIN_RUN2": "no",
    }
    found = subprocess.run(
        ["bash", str(OVERNIGHT), str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert found.returncode == 0, found.stderr
    log = (out / "overnight.log").read_text()
    assert "start sqlglot-general-rerun" in log
    assert "start sqlglot-habits" not in log
    assert "never served: Muse-Glimmer-30B-sqlglot-habits" in log


def test_overnight_waiter_refuses_without_its_inputs(tmp_path):
    env = {
        "PATH": "/usr/bin:/bin",
        "SYMBIONT_GLIMMER_URL": "http://127.0.0.1:1/v1",
        "QUEUE_SUMMARY": str(tmp_path / "q.txt"),
    }
    found = subprocess.run(
        ["bash", str(OVERNIGHT), str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert found.returncode == 66
