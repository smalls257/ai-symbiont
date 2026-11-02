"""MCP stdio server: newline-delimited JSON-RPC 2.0: `recall`, and the curation tools."""

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import IO, Any

from symbiont.delivery.curation_tools import BY_NAME, as_text, listed_tools, route_and_body
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


def serve_stdio(
    stdin: IO[str],
    stdout: IO[str],
    project: str,
    port: int,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Answer requests line by line until stdin closes; only JSON-RPC goes to stdout."""
    host = os.environ if environ is None else environ

    def ask(question: str) -> str:
        """Ask the local service one plain question."""
        return recall_answer(question, project, port)

    def curate(name: str, arguments: dict[str, Any]) -> str:
        """Call one curation route of the local service for this project."""
        route, body = route_and_body(name, arguments, host)
        return as_text(call_service("/" + route, {**body, "project": project}, port))

    for line in stdin:
        if not line.strip():
            continue
        reply = _reply_to_line(line, ask, curate)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def _reply_to_line(
    line: str, ask: Callable[[str], str], curate: Curate | None = None
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
        result = _dispatch(request["method"], request.get("params"), ask, curate)
    except _RpcError as failure:
        return _error(request["id"], failure.code, str(failure))
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def _dispatch(
    method: str, params: Any, ask: Callable[[str], str], curate: Curate | None
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
        return {"tools": [RECALL_TOOL, *listed_tools()]}
    if method == "tools/call":
        return _call_tool(params, ask, curate)
    raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")


def _negotiated(params: Any) -> str:
    """The client's protocol version if supported, else our newest."""
    asked = params.get("protocolVersion") if isinstance(params, dict) else None
    return asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def _call_tool(params: Any, ask: Callable[[str], str], curate: Curate | None) -> dict[str, Any]:
    """Run recall or a curation tool; any other tool name raises _RpcError."""
    name = params.get("name") if isinstance(params, dict) else None
    if name in BY_NAME and curate is not None:
        return _tool_result(_curation_answer(curate, name, params.get("arguments") or {}))
    if name != "recall":
        raise _RpcError(INVALID_PARAMS, f"unknown tool {name!r}")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict) or arguments.keys() != {"question"}:
        return _tool_result(_BAD_ARGUMENTS)
    question = arguments["question"]
    if not isinstance(question, str):
        return _tool_result(_BAD_ARGUMENTS)
    log.info("recall question of %d chars", len(question))
    return _tool_result(_answer(ask, question))


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


def _id_of(request: Any) -> Any:
    """The request id, or None when the request is not an object."""
    return request.get("id") if isinstance(request, dict) else None


def _error(request_id: Any, code: int, reason: str) -> dict[str, Any]:
    """A JSON-RPC error reply."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": reason}}
