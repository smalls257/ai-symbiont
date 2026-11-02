"""A hook that finds the service down starts it once, waits briefly, and otherwise says so.

Failures guarded against: Silent Fallback (an empty note from a dead service) and a process spawn
on every tool call when the service cannot start.
"""

import socket
import threading

import pytest

from symbiont.delivery import launch
from symbiont.delivery.recall import ServiceOfflineError
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import open_service

pytestmark = pytest.mark.periphery

# The conftest replaces launch.start_service for every test; this is the real one.
REAL_START_SERVICE = launch.start_service


def listening(tmp_path):
    httpd = server.bind(open_service(tmp_path / "svc", ServiceMode.WARN_AND_RECALL), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def recall_body():
    return {"question": "anything", "project": "demo"}


def test_a_running_service_is_called_without_starting_anything(tmp_path, monkeypatch):
    httpd = listening(tmp_path)
    started = []
    monkeypatch.setattr(launch, "start_service", lambda data_dir, port: started.append(port))
    try:
        call = launch.reviving_call(tmp_path / "home")
        reply = call("/recall", recall_body(), httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert "answer" in reply and started == []


def test_a_down_service_is_started_once_and_the_call_is_retried(tmp_path, monkeypatch):
    holder = {}

    def start(data_dir, port):
        holder["httpd"] = server.bind(
            open_service(tmp_path / "svc", ServiceMode.WARN_AND_RECALL), port
        )
        threading.Thread(target=holder["httpd"].serve_forever, daemon=True).start()

    monkeypatch.setattr(launch, "start_service", start)
    monkeypatch.setattr(launch, "START_WAIT_S", 2.0)
    free = free_port()
    try:
        reply = launch.reviving_call(tmp_path / "home")("/recall", recall_body(), free)
    finally:
        holder["httpd"].shutdown()
        holder["httpd"].server_close()
    assert "answer" in reply


def test_a_service_that_never_comes_up_is_offline_with_its_log_named(tmp_path):
    with pytest.raises(ServiceOfflineError, match="service.log"):
        launch.reviving_call(tmp_path / "home")("/recall", recall_body(), free_port())


def test_a_crash_looping_service_is_not_started_on_every_call(tmp_path, monkeypatch):
    starts = []
    monkeypatch.setattr(launch, "start_service", lambda data_dir, port: starts.append(port))
    call = launch.reviving_call(tmp_path / "home")
    port = free_port()

    for _ in range(3):
        with pytest.raises(ServiceOfflineError):
            call("/recall", recall_body(), port)

    assert len(starts) == 1


def test_a_missing_symbiont_command_is_offline_naming_the_cause(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ServiceOfflineError, match="could not start"):
        REAL_START_SERVICE(tmp_path / "home", free_port())


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_port_the_service_listens_on_is_the_port_the_clients_use():
    from symbiont.egress.policy import LOCAL_SERVICE_PORT

    assert server.SERVICE_PORT == LOCAL_SERVICE_PORT
