"""The recall client: one plain question to the local service, through the egress door."""

import json

from symbiont.egress import Destination, Endpoint, post_json

TIMEOUT_S = 10.0


class ServiceOfflineError(ConnectionError):
    """The local service could not be reached; the message says where."""


class ServiceRefusedError(RuntimeError):
    """The service answered with a refusal (for example 400); the message is its reason."""


def recall_answer(question: str, project: str, port: int) -> str:
    """The service's answer; raises rather than returning an empty one."""
    url = f"http://127.0.0.1:{port}"
    body = {"question": question, "project": project}
    try:
        reply = post_json(
            Destination(Endpoint.LOCAL_SERVICE, f"{url}/recall"), body, timeout_s=TIMEOUT_S
        )
    except OSError as exc:
        if getattr(exc, "code", None) is None:
            raise ServiceOfflineError(f"could not reach the local service at {url}") from exc
        raise ServiceRefusedError(_reason(exc)) from exc
    return str(reply["answer"])


def _reason(refusal: OSError) -> str:
    """The service's own reason from an error response, else the status line."""
    try:
        return str(json.loads(refusal.read())["error"])  # type: ignore[attr-defined]
    except (AttributeError, ValueError, KeyError):
        return str(refusal)
