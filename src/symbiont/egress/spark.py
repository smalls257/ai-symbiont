"""Meta's OpenAI-compatible chat API as a priced, capped, privacy-checked call.

A reply whose content is None (a reasoning model out of `max_tokens`) raises, never becomes a
move; a refusal, a cap and an API error raise too. Every call that reaches the server lands in the
ledger with tokens and cost, even an empty one, because the tokens were billed.
"""

import json
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
from symbiont.egress.policy import Destination, EgressRefusedError, Endpoint
from symbiont.egress.spend import (
    Ledger,
    LedgerEntry,
    SpendCaps,
    Tier,
    Usage,
    cost_usd,
    estimate_call_usd,
    estimate_usage,
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
    """The server answered, but not with a usable reply (no content, no usage, not JSON)."""

    def __init__(self, message: str, reason: str = "bad_reply"):
        """Keep `reason` so the ledger can record why the reply was unusable."""
        super().__init__(message)
        self.reason = reason  # the ledger's error field for this failure


def _checked_message(out: dict[str, Any], usage: Usage, *, tool_calls_ok: bool) -> dict[str, Any]:
    """The reply's message; raises SparkReplyError for no choices, a refusal or an empty reply."""
    choices = out.get("choices") or []
    if not choices:
        raise SparkReplyError("the reply has no choices", "no_choices")
    choice = choices[0]
    message: dict[str, Any] = choice.get("message") or {}
    reason = choice.get("finish_reason")
    if message.get("refusal") or reason == "content_filter":
        raise SparkReplyError(f"the model refused this request (finish_reason={reason})", "refusal")
    content = message.get("content")
    if tool_calls_ok and message.get("tool_calls"):
        return message
    if content is None or not str(content).strip():
        raise SparkReplyError(
            f"no content (finish_reason={reason}, completion_tokens={usage.completion}, "
            f"reasoning_tokens={usage.reasoning}); raise max_tokens or lower the effort",
            "no_content",
        )
    return message


class SparkApiError(RuntimeError):
    """The server answered with an HTTP error; carries the status and a short server message."""


def _status_of(error: Exception) -> str:
    """The ledger's error field: the HTTP status, the reply problem, or the exception class."""
    if isinstance(error, SparkApiError):
        return str(error).split(":")[0]
    if isinstance(error, SparkReplyError):
        return error.reason
    return type(error).__name__


def _rejected_before_generation(error: Exception) -> bool:
    """A 4xx was refused before the model ran; everything else may have been generated."""
    return isinstance(error, SparkApiError) and str(error).startswith("status 4")


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
        raise SparkReplyError("the server reported no token usage for this reply", "no_usage")
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
        message = _checked_message(out, usage, tool_calls_ok=False)
        finish = str(out["choices"][0].get("finish_reason"))
        return SparkReply(message["content"], finish, usage, seconds)

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
        out, usage, _ = self._priced_call(body, label, declared)
        _checked_message(out, usage, tool_calls_ok=True)
        return out

    def _priced_call(
        self, body: dict[str, Any], label: str, provenance: list[Provenance]
    ) -> tuple[dict[str, Any], Usage, float]:
        """Reserve the worst case under the caps, send, settle (a failed call at an estimate)."""
        worst = estimate_call_usd(self.tier, len(json.dumps(body).encode()), body["max_tokens"])
        call = self.ledger.reserve(self.run, self.caps, worst, label)
        destination = Destination(self.endpoint, CHAT_URL, self.key)
        started = time.monotonic()
        try:
            out = self._send(destination, body, provenance)
            usage = _usage_from(out)
        except EgressRefusedError:
            self.ledger.release(call)  # refused before sending: nothing left, nothing billed
            raise
        except (SparkApiError, SparkReplyError, OSError) as error:
            failed = self._failure_entry(body, label, time.monotonic() - started, error)
            self.ledger.settle(call, failed)
            raise
        seconds = time.monotonic() - started
        entry = LedgerEntry(
            self.run, label, self.model, self.tier, usage, cost_usd(self.tier, usage), seconds
        )
        self.ledger.settle(call, entry)
        return out, usage, seconds

    def _failure_entry(
        self, body: dict[str, Any], label: str, seconds: float, error: Exception
    ) -> LedgerEntry:
        """Billing of a failed call is unknown: an estimate, flagged, never $0."""
        wire_bytes = len(json.dumps(body).encode())
        usage = estimate_usage(
            wire_bytes, body["max_tokens"], generated=not _rejected_before_generation(error)
        )
        return LedgerEntry(
            self.run, label, self.model, self.tier, usage, cost_usd(self.tier, usage), seconds,
            _status_of(error), estimated=True,
        )  # fmt: skip

    def _send(
        self, destination: Destination, body: dict[str, Any], provenance: list[Provenance]
    ) -> dict[str, Any]:
        """Send via post_json; raises SparkApiError (HTTP error) or SparkReplyError (bad JSON)."""
        try:
            return post_json(destination, body, provenance=provenance, transport=self.transport)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:ERROR_EXCERPT_CHARS] if error.fp else ""
            raise SparkApiError(f"status {error.code}: {detail}") from error
        except json.JSONDecodeError:
            raise SparkReplyError("the reply is not valid JSON", "bad_json") from None
