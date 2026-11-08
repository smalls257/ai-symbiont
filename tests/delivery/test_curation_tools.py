"""The curation tools over MCP: one route each, the harness read from the host, failures visible."""

import io
import json
import socket
import threading

import pytest

from symbiont.delivery.curation_tools import TOOLS, route_and_body
from symbiont.delivery.mcp_server import serve_stdio
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import Guards, open_service
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery


def converse(messages, port, environ=None):
    stdout = io.StringIO()
    lines = "\n".join(json.dumps({"jsonrpc": "2.0", **m}) for m in messages) + "\n"
    serve_stdio(io.StringIO(lines), stdout, "demo", port, environ or {})
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def call(name, arguments, request_id=1):
    return {
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


@pytest.fixture
def service(tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance("demo", RepoStance.GIVEN)
    httpd = server.bind(
        open_service(tmp_path, ServiceMode.WARN_AND_RECALL, guards=Guards(repos=registry)), 0
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def test_the_tools_are_listed_with_schemas_and_no_internal_route(tmp_path):
    (reply,) = converse([{"id": 1, "method": "tools/list"}], 1)

    names = [tool["name"] for tool in reply["result"]["tools"]]
    assert names[0] == "recall" and {t["name"] for t in TOOLS} <= set(names)
    assert all("route" not in tool and "inputSchema" in tool for tool in reply["result"]["tools"])
    assert "symbiont_add_lessons" in names and "symbiont_save_reviews" in names


def test_add_lessons_through_the_tool_stores_them_for_the_repository(service):
    port, data = service
    lesson = {"text_in_plain_words": "Refunds never retry.", "kind": "rule", "severity": "high"}

    (reply,) = converse([call("symbiont_add_lessons", {"lessons": [lesson]})], port)

    assert reply["result"]["isError"] is False
    assert json.loads(reply["result"]["content"][0]["text"])["added"] == 1
    assert Store.open(data / "store.db").curation.authored("demo")[0].severity.value == "high"


def test_a_refused_call_is_an_error_the_model_can_read(service):
    port, _ = service

    (reply,) = converse([call("symbiont_add_lessons", {"lessons": [{"kind": "rule"}]})], port)

    assert reply["result"]["isError"] is True
    assert "symbiont refused symbiont_add_lessons" in reply["result"]["content"][0]["text"]


def test_a_down_service_is_said_not_an_empty_result():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    (reply,) = converse([call("symbiont_review_candidates", {})], port)

    assert reply["result"]["content"][0]["text"].startswith("symbiont offline:")


def test_the_harness_comes_from_muse_s_environment_else_from_the_model():
    route, body = route_and_body("symbiont_correction_candidates", {}, {"MUSE_PLUGIN_ROOT": "/x"})
    assert (route, body["running_in"]) == ("corrections/candidates", "muse_code")

    _, body = route_and_body("symbiont_correction_candidates", {"running_in": "claude_code"}, {})
    assert body["running_in"] == "claude_code"
    with pytest.raises(ValueError, match="running_in"):
        route_and_body("symbiont_correction_candidates", {}, {})


@pytest.mark.parametrize("marker", ["CLAUDECODE", "CLAUDE_PLUGIN_ROOT"])
def test_the_harness_is_claude_code_when_its_environment_says_so(marker):
    _, body = route_and_body("symbiont_correction_candidates", {}, {marker: "1"})
    assert body["running_in"] == "claude_code"


def test_muse_wins_when_both_hosts_markers_are_present():
    environ = {"MUSE_PLUGIN_ROOT": "/x", "CLAUDE_PLUGIN_ROOT": "/x"}
    _, body = route_and_body("symbiont_correction_candidates", {}, environ)
    assert body["running_in"] == "muse_code"


def test_the_four_summary_and_topic_tools_are_listed_and_each_is_one_route():
    names = {
        "symbiont_session_candidates": "summaries/candidates",
        "symbiont_save_session_summaries": "summaries/save",
        "symbiont_topic_candidates": "topics/candidates",
        "symbiont_save_topics": "topics/save",
    }
    for name, route in names.items():
        assert route_and_body(name, {"running_in": "claude_code"}, {})[0] == route
    reads_history = [n for n in names if n.endswith("candidates")]
    for name in reads_history:
        assert route_and_body(name, {}, {"CLAUDECODE": "1"})[1]["running_in"] == "claude_code"


def test_a_bad_summary_through_the_tool_is_an_error_that_says_what_to_resend(service):
    port, _ = service
    bad = {"session_id": "x", "goal": "g", "outcome": "great", "noise": False}

    (reply,) = converse([call("symbiont_save_session_summaries", {"summaries": [bad]})], port)

    assert reply["result"]["isError"] is True
    assert "outcome must be one of" in reply["result"]["content"][0]["text"]


def test_the_group_verdict_tools_are_listed_and_each_is_one_route():
    names = {
        "symbiont_group_candidates": "verdicts/candidates",
        "symbiont_save_group_verdicts": "verdicts/save",
    }
    for name, route in names.items():
        assert (
            route_and_body(name, {"project": "demo", "running_in": "claude_code"}, {})[0] == route
        )
    body = route_and_body("symbiont_group_candidates", {}, {"CLAUDECODE": "1"})[1]
    assert body["running_in"] == "claude_code"


def test_the_rule_tools_are_listed_and_each_is_one_route():
    names = {"symbiont_rule_candidates": "rules/candidates", "symbiont_save_rules": "rules/save"}
    for name, route in names.items():
        assert route_and_body(name, {"running_in": "claude_code"}, {})[0] == route
        assert route_and_body(name, {}, {"CLAUDECODE": "1"})[1]["running_in"] == "claude_code"
