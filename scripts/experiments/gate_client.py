"""Send one chat request to Glimmer through the egress door and record its cost."""

import time
from dataclasses import dataclass
from typing import Any

from gate_coding import bash_command

from symbiont.act1.glimmer import REPLY_TEMPERATURE
from symbiont.egress import Destination, Endpoint, post_json

MODEL = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
SAMPLING_SEED = 20261030  # Act 1 sets no sampling seed; the gate fixes one, same for both arms
MAX_TOKENS = 3000  # one cap for both arms and both domains (see the prereg)
REQUEST_TIMEOUT_S = 900.0
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command"}},
            "required": ["command"],
        },
    },
}


@dataclass(frozen=True)
class Completion:
    """What came back: the visible reply, why it stopped, and what it cost."""

    text: str
    command: str | None
    finish_reason: str
    completion_tokens: int
    reasoning_chars: int
    seconds: float


def reasoning_line(strength: str) -> str:
    """Glimmer's documented switch, worded as Act 1 and the calibration word it."""
    return f"Reasoning strength: {strength}"


def read_completion(out: dict[str, Any], seconds: float) -> Completion:
    """Pick the reply, stop reason and token counts out of a chat-completions body."""
    choice = out["choices"][0]
    message = choice["message"]
    return Completion(
        text=(message.get("content") or "").strip(),
        command=bash_command(message),
        finish_reason=choice.get("finish_reason") or "unknown",
        completion_tokens=int(out["usage"]["completion_tokens"]),
        reasoning_chars=len(message.get("reasoning_content") or ""),
        seconds=seconds,
    )


def ask(
    base_url: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> Completion:
    """One request, one at a time; raises on any transport or protocol error (no fallback)."""
    body: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": REPLY_TEMPERATURE,
        "seed": SAMPLING_SEED,
    }
    if tools:
        body["tools"] = tools
    url = base_url.rstrip("/") + "/chat/completions"
    started = time.monotonic()
    out = post_json(Destination(Endpoint.LOCAL_GLIMMER, url), body, timeout_s=REQUEST_TIMEOUT_S)
    return read_completion(out, time.monotonic() - started)
