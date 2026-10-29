"""The recall client: one plain question to the local service, through the egress door."""

import json
from typing import Any

from symbiont.egress import Destination, EgressRefusedError, Endpoint, post_json

TIMEOUT_S = 10.0
# The service answers 503 when the memory model behind it cannot give a note: offline to the user.
UNAVAILABLE = 503


class ServiceOfflineError(ConnectionError):
    """The local service could not be reached; the message says where."""


class ServiceRefusedError(RuntimeError):
    """The service answered with a refusal (for example 400); the message is its reason."""


class ServiceReplyError(ValueError):
    """The service replied without a usable answer."""


def call_service(route: str, body: dict[str, object], port: int) -> dict[str, Any]:
    """POST `body` to the local service; offline and refusal are distinct errors, never a blank."""
    url = f"http://127.0.0.1:{port}"
    try:
        reply = post_json(
            Destination(Endpoint.LOCAL_SERVICE, f"{url}{route}"), body, timeout_s=TIMEOUT_S
        )
    except EgressRefusedError as refusal:
        raise ServiceRefusedError(f"egress policy refused the call: {refusal}") from refusal
    except OSError as exc:
        code = getattr(exc, "code", None)
        if code is None:
            raise ServiceOfflineError(f"could not reach the local service at {url}") from exc
        if code == UNAVAILABLE:
            raise ServiceOfflineError(_reason(exc)) from exc
        raise ServiceRefusedError(_reason(exc)) from exc
    if not isinstance(reply, dict):
        raise ServiceReplyError("the local service sent a reply that is not an object")
    return reply


def recall_answer(question: str, project: str, port: int) -> str:
    """The service's answer; raises rather than returning an empty one."""
    reply = call_service("/recall", {"question": question, "project": project}, port)
    answer = reply.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ServiceReplyError("the local service sent no answer")
    return answer


def _reason(refusal: OSError) -> str:
    """The service's own reason from an error response, else the status line."""
    read = getattr(refusal, "read", None)
    if read is None:
        return str(refusal)
    try:
        return str(json.loads(read())["error"])
    except (ValueError, KeyError):
        return str(refusal)
