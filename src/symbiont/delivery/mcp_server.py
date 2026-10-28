"""MCP stdio server: newline-delimited JSON-RPC 2.0 exposing the one `recall` tool."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Any

from symbiont.delivery.recall import ServiceOfflineError, ServiceRefusedError, recall_answer

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
    text: str
    refused: bool = False


log = logging.getLogger("symbiont.mcp")


class _RpcError(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code


def serve_stdio(stdin: IO[str], stdout: IO[str], project: str, port: int) -> None:
    """Answer requests line by line until stdin closes; only JSON-RPC goes to stdout."""

    def ask(question: str) -> str:
        return recall_answer(question, project, port)

    for line in stdin:
        if not line.strip():
            continue
        reply = _reply_to_line(line, ask)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def _reply_to_line(line: str, ask: Callable[[str], str]) -> dict[str, Any] | None:
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
        result = _dispatch(request["method"], request.get("params"), ask)
    except _RpcError as failure:
        return _error(request["id"], failure.code, str(failure))
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def _dispatch(method: str, params: Any, ask: Callable[[str], str]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": _negotiated(params),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [RECALL_TOOL]}
    if method == "tools/call":
        return _call_tool(params, ask)
    raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")


def _negotiated(params: Any) -> str:
    asked = params.get("protocolVersion") if isinstance(params, dict) else None
    return asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def _call_tool(params: Any, ask: Callable[[str], str]) -> dict[str, Any]:
    if not isinstance(params, dict) or params.get("name") != "recall":
        raise _RpcError(INVALID_PARAMS, "unknown tool; the only tool is recall")
    arguments = params.get("arguments")
    question = arguments.get("question") if isinstance(arguments, dict) else None
    if not isinstance(question, str) or arguments.keys() != {"question"}:
        return _tool_result(
            _Answer("recall needs exactly one argument: question, a string", refused=True)
        )
    log.info("recall question of %d chars", len(question))
    return _tool_result(_answer(ask, question))


def _tool_result(answer: _Answer) -> dict[str, Any]:
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


def _id_of(request: Any) -> Any:
    return request.get("id") if isinstance(request, dict) else None


def _error(request_id: Any, code: int, reason: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": reason}}
