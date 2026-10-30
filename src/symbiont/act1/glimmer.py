"""The Glimmer chat client: one request to the owner's own llama.cpp server.

Violation prevented: Silent Fallback at the privacy boundary. The call goes through
`symbiont.egress`, so a public host is refused and what was sent is logged (sizes only).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from symbiont.egress import Destination, Endpoint, post_json

# Glimmer at "Reasoning strength: low" spent all of 400 tokens thinking on 2 of 10 decisions
# (finish_reason "length", empty content). 1500 leaves room for low reasoning plus a short strategy.
REPLY_MAX_TOKENS = 1500
REPLY_TEMPERATURE = 0.6
REASONING_SYSTEM_MESSAGE = (
    "Reasoning strength: low"  # Muse/Glimmer's documented switch for short thinking
)


@dataclass(frozen=True)
class Reply:
    """What the model said: text, why it stopped, and how much it spent thinking."""

    text: str
    finish_reason: str
    reasoning_chars: int


ReplyFn = Callable[[str], Reply]


def parse_chat_response(out: dict[str, Any]) -> Reply:
    """Read the reply text, finish reason and size of the hidden reasoning."""
    choice = out["choices"][0]
    message = choice["message"]
    return Reply(
        text=(message.get("content") or "").strip(),
        finish_reason=choice.get("finish_reason") or "unknown",
        reasoning_chars=len(message.get("reasoning_content") or ""),
    )


def chat_reply(
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: float = 300.0,
    max_tokens: int = REPLY_MAX_TOKENS,
) -> Reply:
    """Ask the local Glimmer server for one reply, through the egress module."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": REASONING_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": REPLY_TEMPERATURE,
    }
    # Glimmer is the owner's own server, so no provenance is declared; the egress policy still
    # refuses a public host for this endpoint.
    url = base_url.rstrip("/") + "/chat/completions"
    return parse_chat_response(
        post_json(Destination(Endpoint.LOCAL_GLIMMER, url), body, timeout_s=timeout_s)
    )
