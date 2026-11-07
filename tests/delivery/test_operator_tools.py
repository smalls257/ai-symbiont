"""The operator tools over MCP: each runs the `symbiont` subcommand of its name; failures show.

They exist so `/symbiont allow` works where the harness shell is sandboxed away from the data
directory (Muse Code): the MCP server runs outside it.
"""

import io
import json
import socket

import pytest
from tests.live_service import serving

from symbiont import cli
from symbiont.delivery.mcp_operator import _WatchBudget, operate_in_server
from symbiont.delivery.mcp_server import serve_stdio, serve_stdio_operating
from symbiont.delivery.operator_tools import (
    OPERATOR_TOOLS,
    Outcome,
    listed_operator_tools,
    operator_argv,
)
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
EXPECTED = {
    "symbiont_allow",
    "symbiont_decline",
    "symbiont_mine",
    "symbiont_nightly",
    "symbiont_status",
    "symbiont_why",
    "symbiont_lessons",
    "symbiont_dashboard",
    "symbiont_mute",
    "symbiont_forget",
    "symbiont_context",
    "symbiont_settings",
    "symbiont_learn_from_prs",
}


def unused_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def converse(messages, operate, port=1):
    stdout = io.StringIO()
    lines = "\n".join(json.dumps({"jsonrpc": "2.0", **m}) for m in messages) + "\n"
    serve_stdio_operating(io.StringIO(lines), stdout, "demo", port, operate)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def call(name, arguments=None, request_id=1):
    params = {"name": name, "arguments": arguments or {}}
    return {"id": request_id, "method": "tools/call", "params": params}


def test_every_operator_action_is_listed_with_a_schema_and_no_command_inside():
    (reply,) = converse([{"id": 1, "method": "tools/list"}], lambda argv: Outcome(""))

    tools = {tool["name"]: tool for tool in reply["result"]["tools"]}
    assert set(tools) >= EXPECTED and {t.name for t in OPERATOR_TOOLS} == EXPECTED
    assert all(set(t) == {"name", "description", "inputSchema"} for t in listed_operator_tools())
    assert tools["symbiont_context"]["inputSchema"]["required"] == ["lesson", "words"]


def test_the_server_without_an_operator_offers_no_operator_tools():
    stdout = io.StringIO()
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    serve_stdio(io.StringIO(request + "\n"), stdout, "demo", 1)

    names = [tool["name"] for tool in json.loads(stdout.getvalue())["result"]["tools"]]
    assert not EXPECTED & set(names)


@pytest.mark.parametrize(
    ("name", "arguments", "argv"),
    [
        ("symbiont_allow", {}, ["repo", "allow", "--project", "demo"]),
        ("symbiont_decline", {}, ["repo", "decline", "--project", "demo"]),
        ("symbiont_mine", {}, ["repo", "mine", "--project", "demo", "--port", "7"]),
        ("symbiont_status", {}, ["status", "--project", "demo", "--port", "7"]),
        ("symbiont_dashboard", {}, ["dashboard", "--project", "demo", "--port", "7"]),
        (
            "symbiont_dashboard",
            {"view": "trends"},
            ["dashboard", "trends", "--project", "demo", "--port", "7"],
        ),
        ("symbiont_why", {}, ["why", "--project", "demo"]),
        ("symbiont_mute", {}, ["mute", "--project", "demo"]),
        ("symbiont_lessons", {}, ["lessons", "--project", "demo"]),
        ("symbiont_settings", {}, ["settings", "show", "--project", "demo"]),
        ("symbiont_learn_from_prs", {}, ["learn-from-prs", "--project", "demo"]),
        ("symbiont_nightly", {}, ["nightly", "start", "--project", "demo"]),
        (
            "symbiont_nightly",
            {"base": "/b", "kit": "/k"},
            ["nightly", "start", "--project", "demo", "--base", "/b", "--kit-files", "/k"],
        ),
        ("symbiont_forget", {}, ["forget", "--project", "demo"]),
        (
            "symbiont_forget",
            {"lesson_id": "abc"},
            ["forget", "--project", "demo", "--lesson", "abc"],
        ),
        (
            "symbiont_context",
            {"lesson": "last", "words": "on purpose", "intentional": True, "priority": "high"},
            [
                "context",
                "add",
                "last",
                "on purpose",
                "--project",
                "demo",
                "--intentional",
                "--priority",
                "high",
            ],
        ),  # fmt: skip
    ],
)
def test_a_tool_call_runs_the_subcommand_of_the_same_name(name, arguments, argv):
    assert operator_argv(name, arguments, "demo", 7) == argv


def test_every_tool_argv_is_accepted_by_the_real_parser():
    for tool in OPERATOR_TOOLS:
        args = {"lesson": "last", "words": "w"} if tool.name == "symbiont_context" else {}
        argv = operator_argv(tool.name, args, "demo", 7)
        assert cli._parser().parse_args(argv).command == tool.command[0]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("symbiont_allow", {"extra": 1}),
        ("symbiont_context", {"lesson": "last"}),
        ("symbiont_context", {"lesson": "last", "words": "x", "priority": "urgent"}),
        ("symbiont_forget", {"lesson_id": 5}),
        ("symbiont_nightly", {"base": "/b"}),
        ("symbiont_nightly", {"kit": "/k"}),
    ],
)
def test_bad_arguments_are_a_visible_refusal_and_run_nothing(name, arguments):
    ran = []
    (reply,) = converse([call(name, arguments)], lambda argv: ran.append(argv) or Outcome(""))

    assert reply["result"]["isError"] is True and not ran
    assert reply["result"]["content"][0]["text"].startswith(f"symbiont refused {name}")


def test_what_the_subcommand_printed_is_the_answer_and_its_failure_is_an_error():
    outcomes = iter([Outcome("demo: symbiont is on."), Outcome("run allow first", failed=True)])
    first, second = converse(
        [call("symbiont_allow", request_id=1), call("symbiont_mine", request_id=2)],
        lambda argv: next(outcomes),
    )

    assert first["result"] == {
        "content": [{"type": "text", "text": "demo: symbiont is on."}],
        "isError": False,
    }
    assert second["result"]["isError"] is True


@pytest.fixture
def in_process(tmp_path):
    run = operate_in_server(cli.main, watch_s=0)

    def operate(argv):
        return run([*argv, "--data-dir", str(tmp_path)])

    return operate, tmp_path


def test_allow_through_the_tool_records_the_answer_like_the_command_line(in_process):
    operate, data = in_process
    (allowed,) = converse([call("symbiont_allow")], operate)
    (shown,) = converse([call("symbiont_decline")], operate)

    assert "symbiont is on" in allowed["result"]["content"][0]["text"]
    assert allowed["result"]["isError"] is False
    assert "stays off" in shown["result"]["content"][0]["text"]
    assert RepoRegistry(data).stance("demo") is RepoStance.DECLINED


def test_mine_before_allow_says_so_instead_of_returning_nothing(in_process):
    operate, _ = in_process
    (reply,) = converse([call("symbiont_mine")], operate)

    assert reply["result"]["isError"] is True
    assert "symbiont repo allow" in reply["result"]["content"][0]["text"]


def test_the_dashboard_tool_returns_the_address_of_the_view_asked_for(in_process):
    operate, data = in_process
    with serving(data) as (_, port):
        (overview,) = converse([call("symbiont_dashboard")], operate, port=port)
        (topics,) = converse([call("symbiont_dashboard", {"view": "topics"})], operate, port=port)
        (bad,) = converse([call("symbiont_dashboard", {"view": "nope"})], operate, port=port)

    base = f"http://127.0.0.1:{port}/dashboard?project=demo"
    assert overview["result"]["content"][0]["text"] == base + "&view=struggle"
    assert topics["result"]["content"][0]["text"] == base + "&view=topics"
    assert bad["result"]["isError"] is True


def test_a_lessons_listing_of_an_empty_repository_says_so(in_process):
    operate, _ = in_process
    (reply,) = converse([call("symbiont_lessons")], operate)

    assert "no stored lessons for demo" in reply["result"]["content"][0]["text"]


def test_a_status_with_the_service_down_is_offline_not_empty(in_process):
    operate, _ = in_process
    port = unused_port()
    (reply,) = converse([call("symbiont_status")], operate, port=port)

    assert reply["result"]["content"][0]["text"].startswith("symbiont offline:")


def test_stdout_stays_json_rpc_only_while_a_subcommand_prints(in_process, capsys):
    operate, _ = in_process
    converse([call("symbiont_allow")], operate)

    assert capsys.readouterr().out == ""


def test_an_argparse_exit_is_a_failure_with_its_message_not_a_crash():
    def exits(argv, mine_pause):
        raise SystemExit(2)

    outcome = operate_in_server(exits)(["nonsense"])

    assert outcome.failed and outcome.text == "(no output)"


def test_the_mine_wait_is_bounded_and_ends_like_a_ctrl_c_in_the_terminal():
    pause = _WatchBudget(0.01)
    pause(0.02)

    with pytest.raises(KeyboardInterrupt):
        pause(0.02)
