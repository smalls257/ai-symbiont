import io
import json
import socket

import pytest

from symbiont import cli
from symbiont.delivery import mcp_server
from symbiont.delivery.mcp_server import RECALL_TOOL, serve_stdio

pytestmark = pytest.mark.periphery


def unused_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def rpc(method, request_id=None, params=None):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def converse(lines, port=None):
    stdout = io.StringIO()
    serve_stdio(io.StringIO("\n".join(lines) + "\n"), stdout, "p", port or unused_port())
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_tool_schema_has_one_string_param():
    schema = RECALL_TOOL["inputSchema"]
    assert schema["properties"].keys() == {"question"}
    assert schema["properties"]["question"]["type"] == "string"
    assert schema["required"] == ["question"]
    assert RECALL_TOOL["description"].startswith("Ask what went wrong last time")


def test_service_down_returns_offline_text():
    call = rpc("tools/call", 1, {"name": "recall", "arguments": {"question": "what failed?"}})
    port = unused_port()
    (reply,) = converse([call], port)
    result = reply["result"]
    text = result["content"][0]["text"]
    assert text.startswith("symbiont offline: could not reach the local service at ")
    assert f"127.0.0.1:{port}" in text
    assert result["isError"] is False


def test_full_round_trip(monkeypatch):
    monkeypatch.setattr(mcp_server, "recall_answer", lambda question, project, port: "rework: a.py")
    replies = converse(
        [
            rpc("initialize", 1, {"protocolVersion": "2025-11-25", "capabilities": {}}),
            rpc("notifications/initialized"),
            rpc("ping", 2),
            rpc("tools/list", 3),
            rpc("tools/call", 4, {"name": "recall", "arguments": {"question": "q"}}),
        ]
    )
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4]
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert replies[1]["result"] == {}
    assert replies[2]["result"]["tools"] == [RECALL_TOOL]
    assert replies[3]["result"]["content"] == [{"type": "text", "text": "rework: a.py"}]


def test_unknown_method_and_bad_json_do_not_stop_the_loop():
    replies = converse([rpc("resources/list", 1), "{not json", "[1]", rpc("ping", 2)])
    assert replies[0]["error"]["code"] == -32601
    assert replies[1]["error"]["code"] == -32700 and replies[1]["id"] is None
    assert replies[2]["error"]["code"] == -32600
    assert replies[3]["result"] == {}


def test_unknown_tool_is_invalid_params():
    (reply,) = converse([rpc("tools/call", 1, {"name": "other", "arguments": {}})])
    assert reply["error"]["code"] == -32602


@pytest.mark.parametrize("arguments", [{}, {"question": 5}, {"question": "x", "extra": 1}])
def test_bad_arguments_are_a_visible_error_result(arguments):
    (reply,) = converse([rpc("tools/call", 1, {"name": "recall", "arguments": arguments})])
    assert reply["result"]["isError"] is True
    assert reply["result"]["content"][0]["text"].startswith("recall needs exactly one argument")


@pytest.mark.parametrize(
    ("asked", "answered"), [("2025-06-18", "2025-06-18"), ("1999-01-01", "2025-11-25")]
)
def test_initialize_negotiates_the_protocol_version(asked, answered):
    (reply,) = converse([rpc("initialize", 1, {"protocolVersion": asked})])
    assert reply["result"]["protocolVersion"] == answered


def test_unexpected_failure_is_visible_and_the_loop_survives(monkeypatch):
    def broken(question, project, port):
        raise KeyError("answer")

    monkeypatch.setattr(mcp_server, "recall_answer", broken)
    call = rpc("tools/call", 1, {"name": "recall", "arguments": {"question": "q"}})
    failed, pong = converse([call, rpc("ping", 2)])
    assert failed["result"]["isError"] is True
    assert failed["result"]["content"][0]["text"] == "symbiont error: KeyError"
    assert pong["result"] == {}


def test_stdout_is_only_json_rpc_and_logs_omit_the_question(capsys, caplog):
    caplog.set_level("INFO", logger="symbiont.mcp")
    secret = "SECRET-QUESTION-TEXT"
    call = rpc("tools/call", 1, {"name": "recall", "arguments": {"question": secret}})
    converse([call, "{bad"])
    out = capsys.readouterr().out
    assert out == ""
    assert secret not in caplog.text and "question of 20 chars" in caplog.text


def test_mcp_command_serves_stdin_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(rpc("ping", 7) + "\n"))
    assert cli.main(["mcp", "--port", str(unused_port())]) == 0
    assert json.loads(capsys.readouterr().out) == {"jsonrpc": "2.0", "id": 7, "result": {}}
