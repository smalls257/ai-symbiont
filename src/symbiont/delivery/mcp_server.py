"""MCP stdio server: newline-delimited JSON-RPC 2.0: `recall`, and the curation tools."""

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import IO, Any

from symbiont.delivery.curation_tools import BY_NAME, as_text, listed_tools, route_and_body
from symbiont.delivery.operator_tools import (
    OPERATOR_BY_NAME,
    Operate,
    Outcome,
    listed_operator_tools,
    operator_argv,
)
from symbiont.delivery.recall import (
    ServiceOfflineError,
    ServiceRefusedError,
    call_service,
    recall_answer,
)

# Newest first. recall uses only tools/list and tools/call, identical in all of these.
SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "symbiont", "version": "0.1.0"}
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602

RECALL_TOOL = {
    "name": "recall",
    "description": "Ask what went wrong last time in this project.",
    "inputSchema": {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "What you want to know."}},
        "required": ["question"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class _Answer:
    """A tool answer and whether it is a refusal."""

    text: str
    refused: bool = False


_BAD_ARGUMENTS = _Answer("recall needs exactly one argument: question, a string", refused=True)
log = logging.getLogger("symbiont.mcp")


class _RpcError(Exception):
    """A JSON-RPC error with its code."""

    def __init__(self, code: int, reason: str) -> None:
        """Carry the JSON-RPC error code with the reason."""
        super().__init__(reason)
        self.code = code


Curate = Callable[[str, dict[str, Any]], str]
Operator = Callable[[str, dict[str, Any]], Outcome]


def serve_stdio(
    stdin: IO[str],
    stdout: IO[str],
    project: str,
    port: int,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Answer requests line by line until stdin closes; only JSON-RPC goes to stdout."""
    _serve(stdin, stdout, (project, port), environ, None)


def serve_stdio_operating(
    stdin: IO[str], stdout: IO[str], project: str, port: int, operate: Operate
) -> None:
    """`serve_stdio` that also offers the operator tools, which run through `operate`."""
    _serve(stdin, stdout, (project, port), None, operate)


def _serve(
    stdin: IO[str],
    stdout: IO[str],
    where: tuple[str, int],
    environ: Mapping[str, str] | None,
    operate: Operate | None,
) -> None:
    """The request loop; `where` is the project and the service port."""
    project, port = where
    host = os.environ if environ is None else environ

    def ask(question: str) -> str:
        """Ask the local service one plain question."""
        return recall_answer(question, project, port)

    def curate(name: str, arguments: dict[str, Any]) -> str:
        """Call one curation route of the local service for this project."""
        route, body = route_and_body(name, arguments, host)
        return as_text(call_service("/" + route, {**body, "project": project}, port))

    operating = None if operate is None else _operator_for(operate, project, port)
    for line in stdin:
        if not line.strip():
            continue
        reply = _reply_to_line(line, ask, curate, operating)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def _operator_for(operate: Operate, project: str, port: int) -> Operator:
    """The operator tools of one project: each call runs the `symbiont` subcommand it stands for."""

    def operator(name: str, arguments: dict[str, Any]) -> Outcome:
        """Run one operator action."""
        return operate(operator_argv(name, arguments, project, port))

    return operator


def _reply_to_line(
    line: str,
    ask: Callable[[str], str],
    curate: Curate | None = None,
    operator: Operator | None = None,
) -> dict[str, Any] | None:
    """The JSON-RPC reply to one input line; None for notifications."""
    try:
        request = json.loads(line)
    except ValueError:
        log.warning("malformed JSON, %d chars", len(line))
        return _error(None, PARSE_ERROR, "parse error")
    if not isinstance(request, dict) or not isinstance(request.get("method"), str):
        return _error(_id_of(request), INVALID_REQUEST, "invalid request")
    if "id" not in request:
        log.info("notification %s", request["method"])
        return None
    try:
        result = _dispatch(request["method"], request.get("params"), ask, curate, operator)
    except _RpcError as failure:
        return _error(request["id"], failure.code, str(failure))
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def _dispatch(
    method: str,
    params: Any,
    ask: Callable[[str], str],
    curate: Curate | None,
    operator: Operator | None,
) -> dict[str, Any]:
    """Result of one JSON-RPC method; unknown methods raise _RpcError."""
    if method == "initialize":
        return {
            "protocolVersion": _negotiated(params),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        offered = listed_operator_tools() if operator is not None else []
        return {"tools": [RECALL_TOOL, *listed_tools(), *offered]}
    if method == "tools/call":
        return _call_tool(params, ask, curate, operator)
    raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")


def _negotiated(params: Any) -> str:
    """The client's protocol version if supported, else our newest."""
    asked = params.get("protocolVersion") if isinstance(params, dict) else None
    return asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def _call_tool(
    params: Any, ask: Callable[[str], str], curate: Curate | None, operator: Operator | None
) -> dict[str, Any]:
    """Run recall, a curation tool or an operator tool; any other tool name raises _RpcError."""
    name = params.get("name") if isinstance(params, dict) else None
    arguments = params.get("arguments") if isinstance(params, dict) else None
    if isinstance(name, str) and name in OPERATOR_BY_NAME and operator is not None:
        return _tool_result(_operator_answer(operator, name, arguments or {}))
    if isinstance(name, str) and name in BY_NAME and curate is not None:
        return _tool_result(_curation_answer(curate, name, arguments or {}))
    if name != "recall":
        raise _RpcError(INVALID_PARAMS, f"unknown tool {name!r}")
    return _tool_result(_recall_answer(ask, arguments))


def _recall_answer(ask: Callable[[str], str], arguments: Any) -> _Answer:
    """Answer one recall call; anything but exactly one string `question` is a visible refusal."""
    if not isinstance(arguments, dict) or arguments.keys() != {"question"}:
        return _BAD_ARGUMENTS
    question = arguments["question"]
    if not isinstance(question, str):
        return _BAD_ARGUMENTS
    log.info("recall question of %d chars", len(question))
    return _answer(ask, question)


def _tool_result(answer: _Answer) -> dict[str, Any]:
    """Wrap an answer as MCP tool content."""
    return {"content": [{"type": "text", "text": answer.text}], "isError": answer.refused}


def _answer(ask: Callable[[str], str], question: str) -> _Answer:
    """What the model sees. Offline is a plain note; every failure is visible, never silent."""
    try:
        return _Answer(ask(question))
    except ServiceOfflineError as offline:
        log.warning("service offline: %s", offline)
        return _Answer(f"symbiont offline: {offline}")
    except ServiceRefusedError as refused:
        return _Answer(f"symbiont refused the question: {refused}", refused=True)
    except Exception as failure:  # noqa: BLE001 - logged and shown as an error; the loop must live
        kind = type(failure).__name__
        log.error("recall failed: %s", kind)
        return _Answer(f"symbiont error: {kind}", refused=True)


def _curation_answer(curate: Curate, name: str, arguments: Any) -> _Answer:
    """A curation tool's answer; offline and refusals are visible, never an empty result."""
    if not isinstance(arguments, dict):
        return _Answer(f"{name} needs an object of arguments", refused=True)
    try:
        return _Answer(curate(name, arguments))
    except ServiceOfflineError as offline:
        return _Answer(f"symbiont offline: {offline}")
    except (ServiceRefusedError, ValueError) as refused:
        return _Answer(f"symbiont refused {name}: {refused}", refused=True)


def _operator_answer(operator: Operator, name: str, arguments: Any) -> _Answer:
    """An operator tool's answer: what the subcommand printed; a failure is a visible error."""
    if not isinstance(arguments, dict):
        return _Answer(f"{name} needs an object of arguments", refused=True)
    try:
        outcome = operator(name, arguments)
    except ValueError as refused:
        return _Answer(f"symbiont refused {name}: {refused}", refused=True)
    return _Answer(outcome.text, refused=outcome.failed)


def _id_of(request: Any) -> Any:
    """The request id, or None when the request is not an object."""
    return request.get("id") if isinstance(request, dict) else None


def _error(request_id: Any, code: int, reason: str) -> dict[str, Any]:
    """A JSON-RPC error reply."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": reason}}
