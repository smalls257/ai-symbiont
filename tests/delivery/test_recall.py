import socket
import threading

import pytest

from symbiont import cli
from symbiont.delivery.recall import ServiceOfflineError, ServiceRefusedError, recall_answer
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import open_service

pytestmark = pytest.mark.periphery


@pytest.fixture
def port(tmp_path):
    httpd = server.bind(open_service(tmp_path, ServiceMode.WARN_AND_RECALL), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def unused_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_recall_prints_the_services_answer(port, capsys):
    assert cli.main(["recall", "what failed?", "--project", "p", "--port", str(port)]) == 0
    assert capsys.readouterr().out.strip() == "no history for this project yet"


def test_offline_service_prints_a_visible_note_and_exits_zero(capsys):
    free = unused_port()
    assert cli.main(["recall", "what failed?", "--port", str(free)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("symbiont offline: could not reach the local service at ")
    assert f"127.0.0.1:{free}" in out


def test_offline_is_an_error_the_client_raises_not_an_empty_answer():
    with pytest.raises(ServiceOfflineError):
        recall_answer("what failed?", "p", unused_port())


def test_a_refusal_carries_the_services_reason(port):
    with pytest.raises(ServiceRefusedError, match="question and project must be text"):
        recall_answer(123, "p", port)  # type: ignore[arg-type]


def test_serve_passes_port_and_mode_to_the_listener(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve", lambda service, port: seen.update(port=port))
    argv = ["serve", "--port", "0", "--data-dir", str(tmp_path), "--mode", "recall_only"]
    assert cli.main(argv) == 0
    assert seen == {"port": 0} and (tmp_path / "store.db").exists()


def test_open_service_logs_each_call_into_a_run_directory(tmp_path):
    service = open_service(tmp_path, ServiceMode.RECALL_ONLY)
    assert service.respond("/recall", {"question": "q", "project": "p"}).status == 200
    (events,) = (tmp_path / "runs").glob("*/events.jsonl")
    assert '"hook": "recall"' in events.read_text()


@pytest.mark.parametrize("reply", [{}, {"answer": None}, {"answer": ""}, {"answer": 3}])
def test_a_reply_without_a_usable_answer_raises(monkeypatch, reply):
    from symbiont.delivery import recall
    from symbiont.delivery.recall import ServiceReplyError

    monkeypatch.setattr(recall, "post_json", lambda destination, body, timeout_s: reply)
    with pytest.raises(ServiceReplyError):
        recall_answer("q", "p", 1)
