"""The judge client: one loopback `plug_judge_server.py` that answers the mean P(yes).

POST /score {"pairs": [{"system", "prompt"}]} -> {"p_yes": [...]}. The first-night server holds the
three round-3 seed adapters and averages them; a repository's nightly server holds its one adapter.
An unreachable server or a reply without a number raises `JudgeOfflineError` (a
`MemoryModelOfflineError`: the service answers 503, the hook prints "symbiont offline").
"""

from dataclasses import dataclass
from typing import Any

from symbiont.core.judge_format import JUDGE_SYSTEM
from symbiont.egress import Destination, EgressRefusedError, Endpoint, check_outbound, post_json
from symbiont.egress.client import Transport
from symbiont.service.memory_model import MemoryModelOfflineError

# Three adapters on a laptop, 1B model, one pair: seconds, not milliseconds.
TIMEOUT_S = 60.0


class JudgeOfflineError(MemoryModelOfflineError):
    """The judge cannot give a P(yes): unreachable server or an unusable reply."""


@dataclass(frozen=True)
class JudgeModel:
    """A loopback judge server."""

    url: str
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None

    def __post_init__(self) -> None:
        """Refuse a non-loopback URL at launch (EgressRefusedError)."""
        check_outbound(self._destination())

    def _destination(self) -> Destination:
        return Destination(Endpoint.LOCAL_MEMORY_MODEL, self.url.rstrip("/") + "/score")

    def p_yes(self, prompt: str) -> float:
        """The server's mean P(yes) for one judge user message."""
        body = {"pairs": [{"system": JUDGE_SYSTEM, "prompt": prompt}]}
        try:
            if self.transport is None:
                reply = post_json(self._destination(), body, timeout_s=TIMEOUT_S)
            else:
                reply = post_json(
                    self._destination(), body, timeout_s=TIMEOUT_S, transport=self.transport
                )
        except EgressRefusedError:
            raise
        except (OSError, ValueError) as failed:
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
