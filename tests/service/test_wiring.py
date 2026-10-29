import json

import pytest

from symbiont import cli
from symbiont.core.features import N_FEATURES
from symbiont.core.warner import LogisticWarner, WarnerWeightsError
from symbiont.service.wiring import MemorySetupError, load_warner, open_memory, trained_projects

pytestmark = pytest.mark.periphery

WEIGHTS = {
    "mean": [0.0] * N_FEATURES,
    "scale": [1.0] * N_FEATURES,
    "coef": [0.0] * (N_FEATURES + 1),
    "note_at": 0.4,
}


def memory_dir(tmp_path, *projects, adapter=True):
    root = tmp_path / "memory"
    (root / "manifests").mkdir(parents=True)
    if adapter:
        (root / "adapter").mkdir()
        (root / "adapter" / "adapters.safetensors").write_bytes(b"x")
        (root / "adapter.json").write_text(json.dumps({"model": "m", "provenance": "public"}))
    for i, project in enumerate(projects):
        (root / "manifests" / f"{i}.json").write_text(json.dumps({"project": project}))
    return root


def test_load_warner_reads_a_weights_file(tmp_path):
    path = tmp_path / "warner.json"
    path.write_text(json.dumps(WEIGHTS))
    assert isinstance(load_warner(path), LogisticWarner)


def test_load_warner_refuses_a_file_that_is_not_json(tmp_path):
    path = tmp_path / "warner.json"
    path.write_text("not json")
    with pytest.raises(WarnerWeightsError, match="not JSON"):
        load_warner(path)


def test_trained_projects_come_from_the_manifests(tmp_path):
    assert trained_projects(memory_dir(tmp_path, "a", "b/c")) == frozenset({"a", "b/c"})


def test_a_manifest_that_is_not_json_refuses(tmp_path):
    root = memory_dir(tmp_path, "a")
    (root / "manifests" / "broken.json").write_text("[1, 2")
    with pytest.raises(MemorySetupError, match="not a training manifest"):
        trained_projects(root)


def test_no_adapter_or_no_manifest_refuses(tmp_path):
    with pytest.raises(MemorySetupError, match="no trained adapter"):
        trained_projects(memory_dir(tmp_path / "1", "a", adapter=False))
    with pytest.raises(MemorySetupError, match="no training manifest"):
        trained_projects(memory_dir(tmp_path / "2"))


def test_serve_wires_the_warner_and_the_memory_model(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve", lambda service, port: seen.update(parts=service._parts))
    weights = tmp_path / "warner.json"
    weights.write_text(json.dumps(WEIGHTS))
    argv = ["serve", "--data-dir", str(tmp_path / "data"), "--warner", str(weights)]
    argv += [
        "--memory-url",
        "http://127.0.0.1:8090",
        "--memory-dir",
        str(memory_dir(tmp_path, "p")),
    ]
    assert cli.main(argv) == 0
    assert seen["parts"].decider.name == "logistic"
    assert seen["parts"].memory.knows("p")


def test_serve_refuses_half_a_memory_setting_and_a_bad_weights_file(tmp_path, capsys):
    data = str(tmp_path / "data")
    assert cli.main(["serve", "--data-dir", data, "--memory-url", "http://127.0.0.1:1"]) == 1
    assert "go together" in capsys.readouterr().err
    assert cli.main(["serve", "--data-dir", data, "--warner", str(tmp_path / "none.json")]) == 1
    assert "none.json" in capsys.readouterr().err


def test_an_adapter_without_recorded_provenance_refuses(tmp_path):
    root = memory_dir(tmp_path, "p")
    (root / "adapter.json").unlink()
    with pytest.raises(MemorySetupError, match="provenance"):
        open_memory("http://127.0.0.1:8090", root)
    (root / "adapter.json").write_text(json.dumps({"model": "m", "provenance": "everyone"}))
    with pytest.raises(MemorySetupError, match="provenance"):
        open_memory("http://127.0.0.1:8090", root)


def test_serve_refuses_a_memory_url_that_is_not_loopback_at_launch(tmp_path, capsys):
    url = "http://" + "192.168." + "1.20:8090"
    argv = ["serve", "--data-dir", str(tmp_path / "data"), "--memory-url", url]
    argv += ["--memory-dir", str(memory_dir(tmp_path, "p"))]
    assert cli.main(argv) == 1
    assert "loopback only" in capsys.readouterr().err


def test_consent_is_given_withdrawn_and_shown(tmp_path, capsys):
    data = ["--data-dir", str(tmp_path)]
    assert cli.main(["consent", "show", *data]) == 0
    assert "own_history_to_spark = withheld" in capsys.readouterr().out
    assert cli.main(["consent", "give", *data]) == 0
    assert "= consent" in capsys.readouterr().out
    assert cli.main(["consent", "withdraw", *data]) == 0
    assert "= withheld" in capsys.readouterr().out
