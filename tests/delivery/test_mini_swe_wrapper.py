import socket
import threading

import pytest

from symbiont.delivery import mini_swe_wrapper
from symbiont.delivery.mini_swe_wrapper import (
    NOTE_TAG,
    NotedEnvironment,
    WrapMode,
    WrapSettings,
    is_tagged,
    recall_question,
)
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import open_service

pytestmark = pytest.mark.periphery


class FakeEnvironment:
    """Hand-written stand-in with mini-SWE-agent's environment interface."""

    config = "fake-config"

    def serialize(self):
        return {"info": {"config": {"environment_type": "fake"}}}

    def __init__(self):
        self.commands = []

    def execute(self, action, cwd="", *, timeout=None):
        self.commands.append(action["command"])
        return {"output": "ran\n", "returncode": 0, "exception_info": ""}


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


def wrapped(mode, port):
    inner = FakeEnvironment()
    return inner, NotedEnvironment(inner, WrapSettings(mode, port, "s1", "demo"))


def test_notes_appended_to_observation(monkeypatch):
    sent = []

    def fake_service(route, body, port):
        sent.append((route, body))
        return {"notes": ["This failed before."]}

    monkeypatch.setattr(mini_swe_wrapper, "call_service", fake_service)
    inner, env = wrapped(WrapMode.NOTES, 1)
    result = env.execute({"command": "pytest -q"})
    assert result["output"] == f"ran\n\n{NOTE_TAG}\nThis failed before."
    assert result["returncode"] == 0 and env.config == "fake-config"
    route, body = sent[0]
    assert route == "/observe" and body["event"] == "PostToolUse"
    record = body["payload"]["record"]
    assert record["command"] == "pytest -q" and record["exit_code"] == 0


def test_no_notes_appends_nothing(monkeypatch):
    monkeypatch.setattr(mini_swe_wrapper, "call_service", lambda route, body, port: {"notes": []})
    _, env = wrapped(WrapMode.NOTES, 1)
    assert env.execute({"command": "ls"})["output"] == "ran\n"


def test_mode_is_coerced_and_a_typo_raises():
    assert WrapSettings("plain", 1, "s", "p").mode is WrapMode.PLAIN
    with pytest.raises(ValueError):
        WrapSettings("plian", 1, "s", "p")


def test_serialize_records_the_arm():
    _, env = wrapped(WrapMode.PLAIN, 1)
    config = env.serialize()["info"]["config"]
    assert config["environment_type"] == "fake"
    assert config["symbiont_wrap"] == {"mode": "plain", "harness": "mini_swe_agent"}


def test_copy_does_not_recurse_on_a_missing_inner():
    bare = NotedEnvironment.__new__(NotedEnvironment)
    with pytest.raises(AttributeError):
        _ = bare.config


def test_recall_command_intercepted(port):
    inner, env = wrapped(WrapMode.NOTES, port)
    result = env.execute({"command": 'symbiont recall "what failed here?"'})
    assert inner.commands == []
    assert result["returncode"] == 0
    assert result["output"] == f"{NOTE_TAG}\nno history for this project yet"


def test_offline_note_when_service_down():
    free = unused_port()
    inner, env = wrapped(WrapMode.NOTES, free)
    observed = env.execute({"command": "ls"})
    assert observed["returncode"] == 0
    assert f"{NOTE_TAG}\nsymbiont offline: could not reach the local service" in observed["output"]
    recalled = env.execute({"command": "symbiont recall why"})
    assert "symbiont offline" in recalled["output"] and recalled["returncode"] == 0


def test_plain_mode_appends_nothing():
    inner, env = wrapped(WrapMode.PLAIN, unused_port())
    assert env.execute({"command": "ls"})["output"] == "ran\n"
    env.execute({"command": "symbiont recall why"})
    assert inner.commands == ["ls", "symbiont recall why"]


def test_wrapper_output_is_tagged_so_readers_can_skip_it():
    _, env = wrapped(WrapMode.NOTES, unused_port())
    assert is_tagged(env.execute({"command": "ls"})["output"])
    assert is_tagged(env.execute({"command": "symbiont recall why"})["output"])
    assert not is_tagged("ran\nsymbiont offline")


def test_recall_without_a_question_is_a_usage_error(port):
    _, env = wrapped(WrapMode.NOTES, port)
    result = env.execute({"command": "symbiont recall"})
    assert result["returncode"] == 2 and "usage" in result["output"]


def test_only_symbiont_recall_is_recognized():
    assert recall_question("symbiont recall a b") == "a b"
    assert recall_question("echo symbiont recall") is None
    assert recall_question("symbiont hook x") is None
    assert recall_question('symbiont recall "quoted one"') == "quoted one"
    assert recall_question("symbiont recallx") is None
    assert recall_question('symbiont recall "q"\nls') is None


def test_newline_after_recall_is_not_a_question():
    assert recall_question("symbiont recall\npytest -q") is None


@pytest.mark.parametrize(
    "command",
    ['symbiont recall "q" && pytest -q', "symbiont recall q; ls", "symbiont recall q | head"],
)
def test_chained_recall_gets_the_usage_error_not_a_dropped_command(command):
    assert recall_question(command) == ""
    _, env = wrapped(WrapMode.NOTES, 1)
    result = env.execute({"command": command})
    assert result["returncode"] == 2 and "usage" in result["output"]


def test_operators_inside_quotes_stay_part_of_the_question():
    assert recall_question('symbiont recall "why a && b?"') == "why a && b?"


def test_trailing_whitespace_does_not_stop_recall_being_answered(port):
    assert recall_question("symbiont recall why\n") == "why"
    inner, env = wrapped(WrapMode.NOTES, port)
    result = env.execute({"command": "symbiont recall why \n\n"})
    assert inner.commands == [] and result["returncode"] == 0
    assert result["output"].startswith(NOTE_TAG)
