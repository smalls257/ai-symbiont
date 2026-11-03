"""The judge server's /reload swaps the served adapter and a bad folder keeps the old one.

Violation prevented: Silent Fallback. A reload that cannot load answers 400 and keeps serving the
old adapter; it never claims `loaded`. torch, peft and transformers are stubbed, so the test needs
no model; the HTTP part runs on a real loopback socket.
"""

import importlib.util
import json
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
pytestmark = pytest.mark.periphery


class FakePeft:
    """Records the adapter calls the server makes."""

    def __init__(self):
        self.calls = []

    def load_adapter(self, path, adapter_name):
        self.calls.append(("load", adapter_name))

    def set_adapter(self, name):
        self.calls.append(("set", name))

    def delete_adapter(self, name):
        self.calls.append(("delete", name))


@pytest.fixture
def server(monkeypatch):
    stubs = {
        "torch": types.ModuleType("torch"),
        "peft": types.SimpleNamespace(PeftModel=object),
        "transformers": types.SimpleNamespace(AutoModelForCausalLM=object, AutoTokenizer=object),
        "score_pairs_torch": types.SimpleNamespace(
            BATCH=1, prompt_of=None, single_token=None, yes_probability=None
        ),
        "train_lora_torch": types.SimpleNamespace(DEVICE="cpu"),
    }
    for name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, name, stub)
    spec = importlib.util.spec_from_file_location(
        "judge_server_under_test", ROUTEA / "plug_judge_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def judge_with(server):
    judge = server.Judge.__new__(server.Judge)
    judge.model, judge.names, judge.generation = FakePeft(), ["s0", "s1", "s2"], 0
    return judge


def test_reload_serves_only_the_new_adapter_and_drops_the_old_ones(server, tmp_path):
    (tmp_path / "adapter_config.json").write_text("{}")
    judge = judge_with(server)
    judge.reload(str(tmp_path))
    assert judge.names == ["n1"]
    assert judge.model.calls == [
        ("load", "n1"),
        ("set", "n1"),
        ("delete", "s0"),
        ("delete", "s1"),
        ("delete", "s2"),
    ]


def test_reload_of_a_folder_without_an_adapter_raises_and_touches_nothing(server, tmp_path):
    judge = judge_with(server)
    with pytest.raises(FileNotFoundError, match="adapter_config.json"):
        judge.reload(str(tmp_path))
    assert judge.names == ["s0", "s1", "s2"] and judge.model.calls == []


def test_the_reload_route_confirms_the_adapter_or_answers_400(server, tmp_path):
    (tmp_path / "adapter_config.json").write_text("{}")
    httpd = HTTPServer(("127.0.0.1", 0), server.requests_for(judge_with(server)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/reload"

    def post(folder):
        request = urllib.request.Request(url, json.dumps({"adapter": str(folder)}).encode())
        try:
            with urllib.request.urlopen(request) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as refused:
            return refused.code, json.loads(refused.read())

    try:
        assert post(tmp_path) == (200, {"loaded": str(tmp_path)})
        status, body = post(tmp_path / "missing")
        assert status == 400 and "adapter_config.json" in body["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()
