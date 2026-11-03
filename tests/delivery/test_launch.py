"""A hook that finds the service down starts it once, waits briefly, and otherwise says so.

Failures guarded against: Silent Fallback (an empty note from a dead service) and a process spawn
on every tool call when the service cannot start.
"""

import socket
import subprocess
import sys
import threading
import time

import pytest

from symbiont.delivery import detached, launch
from symbiont.delivery.detached import detached_spawn_options
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


def test_a_command_the_developer_waits_on_starts_a_down_service_and_waits_for_it(
    tmp_path, monkeypatch
):
    httpd = listening(tmp_path)
    port = httpd.server_address[1]
    real_call = launch.call_service
    started = []

    def down_until_started(route, body, at, timeout_s=10.0):
        if not started:
            raise launch.ServiceUnreachableError("nothing listening")
        return real_call(route, body, at, timeout_s)

    monkeypatch.setattr(launch, "call_service", down_until_started)
    monkeypatch.setattr(launch, "start_service", lambda data_dir, at: started.append(at))
    try:
        reply = launch.patient_call(tmp_path / "home", 5.0)("/recall", recall_body(), port)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert reply["answer"] == "no history for this project yet"


def test_a_service_that_never_comes_up_is_offline_after_the_wait(tmp_path, monkeypatch):
    def down(route, body, at, timeout_s=10.0):
        raise launch.ServiceUnreachableError("nothing listening")

    monkeypatch.setattr(launch, "call_service", down)
    monkeypatch.setattr(launch, "POLL_S", 0.0)

    with pytest.raises(ServiceOfflineError, match="still starting"):
        launch.patient_call(tmp_path / "home", 0.05)("/mine", {}, 1)


def test_a_detached_child_is_made_per_platform_without_the_other_platforms_option():
    windows = detached_spawn_options("win32")
    assert windows == {"creationflags": 0x08 | 0x200 | 0x01000000}
    for posix in ("linux", "darwin"):
        assert detached_spawn_options(posix) == {"start_new_session": True}


def test_the_real_service_start_detaches_with_this_platforms_options(tmp_path, monkeypatch):
    seen = {}

    def popen(command, **options):
        seen["command"], seen["options"] = command, options

    monkeypatch.setattr(subprocess, "Popen", popen)
    REAL_START_SERVICE(tmp_path / "svc", 9)

    assert seen["command"][:2] == ["symbiont", "serve"]
    assert {k: seen["options"][k] for k in detached_spawn_options()} == detached_spawn_options()


def _refusing_breakaway(calls):
    def popen(command, **options):
        calls.append(options)
        if options["creationflags"] & 0x01000000:
            raise PermissionError(13, "Access is denied")

    return popen


def test_a_job_that_forbids_breakaway_gets_one_retry_and_a_loud_warning(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", _refusing_breakaway(calls))

    detached.spawn_detached(lambda **o: subprocess.Popen(["svc"], **o), platform="win32")

    assert [c["creationflags"] for c in calls] == [0x08 | 0x200 | 0x01000000, 0x08 | 0x200]
    assert "may die with the session" in caplog.text


def test_a_missing_executable_is_not_retried_as_a_refused_breakaway(monkeypatch):
    calls = []

    def popen(command, **options):
        calls.append(options)
        raise FileNotFoundError(2, "not found")

    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(FileNotFoundError):
        detached.spawn_detached(lambda **o: subprocess.Popen(["svc"], **o), platform="win32")
    assert len(calls) == 1


def test_a_failed_retry_still_raises(monkeypatch):
    def popen(command, **options):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(PermissionError):
        detached.spawn_detached(lambda **o: subprocess.Popen(["svc"], **o), platform="win32")


def test_a_child_started_with_this_platforms_detach_options_really_runs(tmp_path):
    out = tmp_path / "child.txt"
    code = f"open({str(out)!r}, 'w').write('ran')"
    with (tmp_path / "log").open("wb") as log:
        detached.spawn_detached(
            lambda **detach: subprocess.Popen(
                [sys.executable, "-c", code],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **detach,
            )
        )
    deadline = time.monotonic() + 5
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert out.read_text(encoding="utf-8") == "ran"
