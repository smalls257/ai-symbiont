"""MCP stdio server: newline-delimited JSON-RPC 2.0 exposing the one `recall` tool."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Any

from symbiont.delivery.recall import ServiceOfflineError, ServiceRefusedError, recall_answer

PROTOCOL_VERSION = "2025-11-25"
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
    ask: Callable[[str], str] = lambda question: recall_answer(question, project, port)  # noqa: E731
    for line in stdin:
        if not line.strip():
            continue
        reply = _reply_to_line(line, ask, port)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def _reply_to_line(line: str, ask: Callable[[str], str], port: int) -> dict[str, Any] | None:
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
        result = _dispatch(request["method"], request.get("params"), ask, port)
    except _RpcError as failure:
        return _error(request["id"], failure.code, str(failure))
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def _dispatch(method: str, params: Any, ask: Callable[[str], str], port: int) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [RECALL_TOOL]}
    if method == "tools/call":
        return _call_tool(params, ask, port)
    raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")


def _call_tool(params: Any, ask: Callable[[str], str], port: int) -> dict[str, Any]:
    arguments = params.get("arguments") if isinstance(params, dict) else None
    question = arguments.get("question") if isinstance(arguments, dict) else None
    if not isinstance(params, dict) or params.get("name") != "recall":
        raise _RpcError(INVALID_PARAMS, "unknown tool; the only tool is recall")
    if not isinstance(question, str):
        raise _RpcError(INVALID_PARAMS, "recall needs a question string")
    log.info("recall question of %d chars", len(question))
    answer = _answer(ask, question, port)
    return {"content": [{"type": "text", "text": answer.text}], "isError": answer.refused}


def _answer(ask: Callable[[str], str], question: str, port: int) -> _Answer:
    """What the model sees. Offline is a plain note, a refusal is flagged."""
    try:
        return _Answer(ask(question) or "symbiont returned no answer")
    except ServiceOfflineError as offline:
        log.warning("service offline on port %d", port)
        return _Answer(f"symbiont offline: {offline}")
    except ServiceRefusedError as refused:
        return _Answer(f"symbiont refused the question: {refused}", refused=True)


def _id_of(request: Any) -> Any:
    return request.get("id") if isinstance(request, dict) else None


def _error(request_id: Any, code: int, reason: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": reason}}
