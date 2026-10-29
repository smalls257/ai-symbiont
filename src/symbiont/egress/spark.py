"""Meta's OpenAI-compatible chat API as a priced, capped, privacy-checked call.

A reply whose content is None (a reasoning model out of `max_tokens`) raises, never becomes a
move; a refusal, a cap and an API error raise too. Every call that reaches the server lands in the
ledger with tokens and cost, even an empty one, because the tokens were billed.
"""

import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from symbiont.egress.client import Transport, _urlopen, post_json
from symbiont.egress.credentials import ApiKey
from symbiont.egress.messages import Message, declared_provenance
from symbiont.egress.policy import Destination, Endpoint
from symbiont.egress.spend import (
    Ledger,
    LedgerEntry,
    SpendCaps,
    Tier,
    Usage,
    cost_usd,
)
from symbiont.records.schema import Provenance

CHAT_URL = "https://api.meta.ai/v1/chat/completions"
# Room for the hidden reasoning plus the answer: a 20-token cap returned content=None.
DEFAULT_MAX_TOKENS = 4096
ERROR_EXCERPT_CHARS = 300


class Effort(StrEnum):
    """`reasoning_effort` values the API accepts; "none" is rejected by the server."""

    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class SparkReplyError(RuntimeError):
    """The server answered, but not with a usable reply (no content, or no usage)."""


class SparkApiError(RuntimeError):
    """The server answered with an HTTP error; carries the status and a short server message."""


@dataclass(frozen=True)
class SparkReply:
    """What came back: the text, why it stopped, the token counts and the seconds it took."""

    text: str
    finish_reason: str
    usage: Usage
    seconds: float


def _usage_from(out: dict[str, Any]) -> Usage:
    """Token counts; the details blocks are omitted by the API when zero, so they default to 0."""
    usage = out.get("usage")
    if not usage or "prompt_tokens" not in usage or "completion_tokens" not in usage:
        raise SparkReplyError("the server reported no token usage for this reply")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    return Usage(usage["prompt_tokens"], cached, usage["completion_tokens"], reasoning)


@dataclass(frozen=True)
class SparkSession:
    """One run's door to the API: model, tier, caps, key, ledger and the provenance it declares."""

    model: str
    tier: Tier
    run: str
    caps: SpendCaps
    key: ApiKey
    ledger: Ledger = field(default_factory=Ledger)
    provenance: tuple[Provenance, ...] = ()
    transport: Transport = _urlopen
    temperature: float | None = None  # None: the server's default
    system: str | None = None  # text of a system message sent before the prompt
    endpoint: Endpoint = Endpoint.CONTRIBUTOR  # Wonder runs name Endpoint.WONDER
    turn_max_tokens: int = DEFAULT_MAX_TOKENS  # room for reasoning plus a tool call per turn

    def chat(
        self, prompt: str, effort: Effort, label: str, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> SparkReply:
        """One single-turn call; never returns an empty reply.

        Raises SpendCapError, EgressRefusedError, SparkApiError or SparkReplyError.
        """
        messages = [{"role": "user", "content": prompt}]
        if self.system is not None:
            messages.insert(0, {"role": "system", "content": self.system})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "reasoning_effort": effort.value,
            "max_tokens": max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        out, usage, seconds = self._priced_call(body, label, list(self.provenance))
        return self._reply(out, usage, seconds)

    def converse(
        self,
        messages: Sequence[Message],
        tools: list[dict[str, Any]],
        effort: Effort,
        label: str,
    ) -> dict[str, Any]:
        """One tool-calling turn over a caller-kept history; returns the raw reply.

        Each system, user and tool message declares its provenance or the turn is refused.
        """
        declared = declared_provenance(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [message.wire() for message in messages],
            "tools": tools,
            "reasoning_effort": effort.value,
            "max_tokens": self.turn_max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        out, _, _ = self._priced_call(body, label, declared)
        return out

    def _priced_call(
        self, body: dict[str, Any], label: str, provenance: list[Provenance]
    ) -> tuple[dict[str, Any], Usage, float]:
        """Cap check, send, ledger line; a failed send is in the ledger too."""
        self.ledger.check_before_call(self.run, self.caps)
        destination = Destination(self.endpoint, CHAT_URL, self.key)
        started = time.monotonic()
        try:
            out = self._send(destination, body, provenance)
        except (SparkApiError, urllib.error.URLError, TimeoutError, ConnectionError) as error:
            self._record_failure(label, time.monotonic() - started, error)
            raise
        seconds = time.monotonic() - started
        usage = _usage_from(out)
        cost = cost_usd(self.tier, usage)
        self.ledger.record(
            LedgerEntry(self.run, label, self.model, self.tier, usage, cost, seconds)
        )
        return out, usage, seconds

    def _record_failure(self, label: str, seconds: float, error: Exception) -> None:
        """A failed call is in the ledger too: zero tokens (the API reports none), its status."""
        status = (
            str(error).split(":")[0] if isinstance(error, SparkApiError) else type(error).__name__
        )
        entry = LedgerEntry(
            self.run, label, self.model, self.tier, Usage(0, 0, 0, 0), 0.0, seconds, status
        )
        self.ledger.record(entry)

    def _send(
        self, destination: Destination, body: dict[str, Any], provenance: list[Provenance]
    ) -> dict[str, Any]:
        try:
            return post_json(destination, body, provenance=provenance, transport=self.transport)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:ERROR_EXCERPT_CHARS] if error.fp else ""
            raise SparkApiError(f"status {error.code}: {detail}") from error

    @staticmethod
    def _reply(out: dict[str, Any], usage: Usage, seconds: float) -> SparkReply:
        choice = out["choices"][0]
        content = choice["message"].get("content")
        reason = choice.get("finish_reason")
        if content is None:
            raise SparkReplyError(
                f"no content (finish_reason={reason}, completion_tokens={usage.completion}, "
                f"reasoning_tokens={usage.reasoning}); raise max_tokens or lower the effort"
            )
        return SparkReply(content, str(reason), usage, seconds)
