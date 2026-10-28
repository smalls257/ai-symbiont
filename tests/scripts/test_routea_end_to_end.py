"""Route A end to end on synthetic fixtures, with a stand-in trainer and memory server.

Synthetic session -> mine -> train_memory (a fake LoRA trainer that stores the training rows)
-> a fake OpenAI-compatible server that answers from those rows -> symbiont serve with the
warner -> a failing step's note through the hook CLI and an answer through the MCP tool.
The real MLX run is `scripts/routea/demo.sh`; this test proves the plumbing in about a second.
"""

import argparse
import importlib.util
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from symbiont import cli
from symbiont.core.features import N_FEATURES
from symbiont.core.warner import LogisticWarner, WarnerWeights
from symbiont.delivery.mcp_server import serve_stdio
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.memory_model import MemoryModel
from symbiont.service.wiring import open_service, trained_projects
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
PROJECT = "demo-shop"
FAKE_TRAINER = """#!{python}
import json, pathlib, sys
_, python, model, work, adapter, logs, name = sys.argv
answers = {{}}
for line in pathlib.Path(work, "train.jsonl").read_text().splitlines():
    messages = json.loads(line)["messages"]
    answers[messages[1]["content"]] = messages[2]["content"]
pathlib.Path(adapter).mkdir(parents=True, exist_ok=True)
pathlib.Path(adapter, "adapters.safetensors").write_text(json.dumps(answers))
"""


def load_script(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location(name, ROUTEA / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def fake_memory_server(answers, reply_override=None):
    """An OpenAI-compatible loopback server answering the prompts it was 'trained' on."""

    class Routes(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            prompt = body["messages"][1]["content"]
            text = reply_override or answers.get(prompt, "I do not remember.")
            payload = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Routes)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def always_risky():
    coef = np.zeros(N_FEATURES + 1)
    coef[0] = 5.0
    return LogisticWarner(WarnerWeights(np.zeros(N_FEATURES), np.ones(N_FEATURES), coef, 0.5))


@pytest.fixture
def trained(tmp_path, monkeypatch):
    """History mined and trained; returns (data dir, memory dir, what the trainer stored)."""
    history = tmp_path / "history"
    monkeypatch.setattr(sys, "argv", ["demo_sessions.py", str(history)])
    load_script(monkeypatch, "demo_sessions").main()
    data = tmp_path / "data"
    log = history / f"{PROJECT}.jsonl"
    argv = ["mine", "--project", PROJECT, "--data-dir", str(data), "--source", f"openhands={log}"]
    assert cli.main(argv) == 0
    trainer = tmp_path / "fake_trainer.py"
    trainer.write_text(FAKE_TRAINER.format(python=sys.executable))
    trainer.chmod(0o755)
    memory = tmp_path / "memory"
    args = argparse.Namespace(
        data_dir=data,
        project=PROJECT,
        memory_dir=memory,
        model="stand-in",
        python=Path(sys.executable),
        trainer=trainer,
        epochs=1,
    )
    counts = load_script(monkeypatch, "train_memory").train(args)
    assert counts["lessons_trained"] == counts["lessons_forgotten"] == 3
    stored = json.loads((memory / "adapter" / "adapters.safetensors").read_text())
    return data, memory, stored


def serve_symbiont(data, memory_url, memory_dir):
    memory = MemoryModel(memory_url, trained_projects(memory_dir))
    service = open_service(data, ServiceMode.WARN_AND_RECALL, always_risky(), memory)
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def failing_pytest():
    return {
        "session_id": "live-1",
        "cwd": f"/tmp/{PROJECT}",
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest tests/test_cart.py -q"},
        "error": "ModuleNotFoundError: No module named 'shop'",
    }


def run_hook(monkeypatch, capsys, port):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(failing_pytest())))
    argv = ["hook", "PostToolUseFailure", "--harness", "claude_code", "--port", str(port)]
    code = cli.main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_a_failing_step_gets_the_trained_note_through_the_hook_and_mcp(
    trained, monkeypatch, capsys
):
    data, memory_dir, stored = trained
    assert Store.open(data / "store.db").lessons(PROJECT) == []  # memory is in the weights now
    memory = fake_memory_server(stored)
    symbiont = serve_symbiont(data, f"http://127.0.0.1:{memory.server_address[1]}", memory_dir)
    port = symbiont.server_address[1]
    try:
        code, reply = run_hook(monkeypatch, capsys, port)
        note = reply["hookSpecificOutput"]["additionalContext"]
        assert code == 0 and note.startswith("Happened: `pytest tests/test_cart.py` failed")
        assert "Resolved: you ran `pip install -e .`" in note
        question = "What went wrong last time with `pytest tests/test_cart.py`?"
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "recall", "arguments": {"question": question}},
            },
        ]
        out = io.StringIO()
        serve_stdio(
            io.StringIO("".join(json.dumps(r) + "\n" for r in requests)), out, PROJECT, port
        )
        answer = json.loads(out.getvalue().splitlines()[1])["result"]
        assert answer["isError"] is False and answer["content"][0]["text"] == note
    finally:
        for httpd in (symbiont, memory):
            httpd.shutdown()
            httpd.server_close()


def test_an_unusable_memory_reply_prints_symbiont_offline_never_a_note(
    trained, monkeypatch, capsys
):
    data, memory_dir, stored = trained
    memory = fake_memory_server(stored, reply_override="Sorry, I am not sure.")
    symbiont = serve_symbiont(data, f"http://127.0.0.1:{memory.server_address[1]}", memory_dir)
    try:
        code, reply = run_hook(monkeypatch, capsys, symbiont.server_address[1])
        note = reply["hookSpecificOutput"]["additionalContext"]
        assert code == 0 and note.startswith("symbiont offline: memory model reply unusable")
        assert reply["systemMessage"] == note
    finally:
        for httpd in (symbiont, memory):
            httpd.shutdown()
            httpd.server_close()


def test_training_nothing_new_is_refused_and_forgets_nothing(trained, monkeypatch, tmp_path):
    data, memory_dir, _ = trained
    script = load_script(monkeypatch, "train_memory")
    args = argparse.Namespace(
        data_dir=data,
        project=PROJECT,
        memory_dir=memory_dir,
        model="stand-in",
        python=Path(sys.executable),
        trainer=tmp_path / "fake_trainer.py",
        epochs=1,
    )
    with pytest.raises(script.TrainingRefusedError, match="no untrained lessons"):
        script.train(args)
    args.model = "another-base"
    with pytest.raises(script.TrainingRefusedError):
        script.train(args)


def test_a_failed_training_run_forgets_no_lesson(tmp_path, monkeypatch):
    history = tmp_path / "history"
    monkeypatch.setattr(sys, "argv", ["demo_sessions.py", str(history)])
    load_script(monkeypatch, "demo_sessions").main()
    data = tmp_path / "data"
    log = history / f"{PROJECT}.jsonl"
    cli.main(
        ["mine", "--project", PROJECT, "--data-dir", str(data), "--source", f"openhands={log}"]
    )
    failing = tmp_path / "failing_trainer.py"
    failing.write_text(f"#!{sys.executable}\nraise SystemExit(3)\n")
    failing.chmod(0o755)
    script = load_script(monkeypatch, "train_memory")
    args = argparse.Namespace(
        data_dir=data,
        project=PROJECT,
        memory_dir=tmp_path / "memory",
        model="stand-in",
        python=Path(sys.executable),
        trainer=failing,
        epochs=1,
    )
    with pytest.raises(script.TrainingRefusedError, match="exit 3"):
        script.train(args)
    assert len(Store.open(data / "store.db").lessons(PROJECT)) == 3
    assert list((tmp_path / "memory" / "work").rglob("*.jsonl")) == []  # lesson text is gone
