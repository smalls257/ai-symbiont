"""The judge: adapters on loopback servers, mean P(yes); it never guesses.

An unreachable server, a reply without a yes/no token or a wrong server count raises
`JudgeOfflineError` (a `MemoryModelOfflineError`: the service answers 503, the hook prints
"symbiont offline"). Calls go through `symbiont.egress.post_json`, loopback only.
"""

import math
from dataclasses import dataclass
from typing import Any

from symbiont.core.agree import JUDGE_SEEDS, JUDGE_SYSTEM
from symbiont.egress import Destination, EgressRefusedError, Endpoint, check_outbound, post_json
from symbiont.egress.client import Transport
from symbiont.service.memory_model import SERVER_DEFAULT, MemoryModelOfflineError

TIMEOUT_S = 8.0
# The answer is one token; twenty alternatives always include both "yes" and "no" when trained.
TOP_LOGPROBS = 20


class JudgeOfflineError(MemoryModelOfflineError):
    """The judge cannot give a P(yes): unreachable server, bad reply or wrong server count."""


@dataclass(frozen=True)
class JudgeModel:
    """The loopback judge servers, one per seed adapter."""

    urls: tuple[str, ...]
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None
    # Three for the agree rule; one for a repository's nightly adapter.
    servers: int = JUDGE_SEEDS

    def __post_init__(self) -> None:
        """Refuse a wrong seed count or a non-loopback URL at launch (EgressRefusedError)."""
        if len(self.urls) != self.servers:
            raise JudgeOfflineError(
                f"the judge needs {self.servers} server(s), got {len(self.urls)}"
            )
        for url in self.urls:
            check_outbound(_destination(url))

    def p_yes(self, prompt: str) -> float:
        """Mean over seeds of P(yes) against P(no) for the judge prompt."""
        found = [self._one_seed(url, prompt) for url in self.urls]
        return sum(found) / len(found)

    def _one_seed(self, url: str, prompt: str) -> float:
        """One adapter's P(yes) from its first-token log-probabilities."""
        destination = _destination(url)
        try:
            if self.transport is None:
                reply = post_json(destination, _request(prompt), timeout_s=TIMEOUT_S)
            else:
                reply = post_json(
                    destination, _request(prompt), timeout_s=TIMEOUT_S, transport=self.transport
                )
        except EgressRefusedError:
            raise
        except (OSError, ValueError) as failed:
            raise JudgeOfflineError(f"judge at {url} failed: {type(failed).__name__}") from failed
        return _p_yes(reply, url)


def _destination(url: str) -> Destination:
    """The loopback chat-completions endpoint of one judge server."""
    return Destination(Endpoint.LOCAL_MEMORY_MODEL, url.rstrip("/") + "/v1/chat/completions")


def _request(prompt: str) -> dict[str, object]:
    """A one-token greedy chat request that returns the first token's alternatives."""
    return {
        "model": SERVER_DEFAULT,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1,
        "temperature": 0.0,
        "logprobs": True,
        "top_logprobs": TOP_LOGPROBS,
    }


def _p_yes(reply: dict[str, Any], url: str) -> float:
    """P(yes) / (P(yes) + P(no)) from the first token's alternatives; raises if either is absent."""
    try:
        alternatives = reply["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
        odds = {
            str(entry["token"]).strip().lower(): math.exp(float(entry["logprob"]))
            for entry in reversed(alternatives)
        }
    except (KeyError, IndexError, TypeError, ValueError) as malformed:
        raise JudgeOfflineError(
            f"judge at {url} replied without token log-probabilities"
        ) from malformed
    if "yes" not in odds or "no" not in odds:
        raise JudgeOfflineError(f"judge at {url} did not rank both yes and no")
    return odds["yes"] / (odds["yes"] + odds["no"])
