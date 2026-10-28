"""The recall client: one plain question to the local service, through the egress door."""

import json
from typing import Any

from symbiont.egress import Destination, Endpoint, post_json

TIMEOUT_S = 10.0


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
    except OSError as exc:
        if getattr(exc, "code", None) is None:
            raise ServiceOfflineError(f"could not reach the local service at {url}") from exc
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
    try:
        return str(json.loads(refusal.read())["error"])  # type: ignore[attr-defined]
    except (AttributeError, ValueError, KeyError):
        return str(refusal)
