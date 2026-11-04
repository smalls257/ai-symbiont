"""The judge client: one loopback `plug_judge_server.py` that answers the mean P(yes).

POST /score {"pairs": [{"system", "prompt"}]} -> {"p_yes": [...]}. The first-night server holds the
three round-3 seed adapters and averages them; a repository's nightly server holds its one adapter.
An unreachable server or a reply without a number raises `JudgeOfflineError` (a
`MemoryModelOfflineError`: the service answers 503, the hook prints "symbiont offline").
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from symbiont.core.judge_format import JUDGE_SYSTEM
from symbiont.egress import Destination, EgressRefusedError, Endpoint, check_outbound, post_json
from symbiont.egress.client import Transport
from symbiont.service.memory_model import MemoryModelOfflineError

# Three adapters on a laptop, 1B model, one pair: seconds, not milliseconds.
TIMEOUT_S = 60.0
# Loading an adapter reads about 40 MB and rebuilds nothing else, but a cold disk is slow.
RELOAD_TIMEOUT_S = 120.0


class JudgeOfflineError(MemoryModelOfflineError):
    """The judge cannot give a P(yes): unreachable server or an unusable reply."""


class JudgeSlowError(JudgeOfflineError):
    """The judge is running but did not answer within the caller's time budget."""


@dataclass(frozen=True)
class JudgeModel:
    """A loopback judge server."""

    url: str
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None
    # How long one score may take; a hook passes a budget far below the default.
    timeout_s: float = TIMEOUT_S

    def __post_init__(self) -> None:
        """Refuse a non-loopback URL at launch (EgressRefusedError)."""
        check_outbound(self._destination())

    def _destination(self) -> Destination:
        return Destination(Endpoint.LOCAL_MEMORY_MODEL, self.url.rstrip("/") + "/score")

    def reload(self, adapter: Path) -> None:
        """Ask the server to serve the adapter in `adapter` from now on.

        Raises JudgeOfflineError when the server is unreachable or does not confirm that exact
        adapter, so a night never believes a stale adapter is live.
        """
        target = Destination(Endpoint.LOCAL_MEMORY_MODEL, self.url.rstrip("/") + "/reload")
        try:
            reply = self._post(target, {"adapter": str(adapter)}, RELOAD_TIMEOUT_S)
        except EgressRefusedError:
            raise
        except (OSError, ValueError) as failed:
            raise JudgeOfflineError(
                f"judge at {self.url} would not reload: {type(failed).__name__}"
            ) from failed
        if not isinstance(reply, dict) or reply.get("loaded") != str(adapter):
            raise JudgeOfflineError(f"judge at {self.url} did not confirm the adapter")

    def _post(self, target: Destination, body: dict[str, Any], timeout_s: float) -> Any:
        """One POST through the egress door, with the test transport when one was given."""
        if self.transport is None:
            return post_json(target, body, timeout_s=timeout_s)
        return post_json(target, body, timeout_s=timeout_s, transport=self.transport)

    def p_yes(self, prompt: str) -> float:
        """The server's mean P(yes) for one judge user message."""
        body = {"pairs": [{"system": JUDGE_SYSTEM, "prompt": prompt}]}
        try:
            reply = self._post(self._destination(), body, self.timeout_s)
        except EgressRefusedError:
            raise
        except (OSError, ValueError) as failed:
            if isinstance(failed, TimeoutError) or isinstance(
                getattr(failed, "reason", None), TimeoutError
            ):
                raise JudgeSlowError(
                    f"judge at {self.url} did not answer within {self.timeout_s:.2f}s"
                ) from failed
            raise JudgeOfflineError(
                f"judge at {self.url} failed: {type(failed).__name__}"
            ) from failed
        return _single_p_yes(reply, self.url)


def _single_p_yes(reply: Any, url: str) -> float:
    """The one P(yes) of a /score reply; anything else raises."""
    try:
        value = reply["p_yes"][0]
        if isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(value)
        return float(value)
    except (KeyError, IndexError, TypeError, ValueError) as malformed:
        raise JudgeOfflineError(f"judge at {url} replied without a P(yes)") from malformed
