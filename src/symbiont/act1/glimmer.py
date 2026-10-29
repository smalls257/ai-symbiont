"""The Glimmer chat client: one request to the owner's own llama.cpp server.

Violation prevented: Silent Fallback at the privacy boundary. The call goes through
`symbiont.egress`, so a public host is refused and what was sent is logged (sizes only).

Violation prevented: Paper Tiger in the plain-versus-personal comparison. Both arms are a
`GlimmerArm` on one llama-server that holds the Freedoom adapter; they differ only in the adapter
scales sent with every request (plain: all 0, personal: its adapter at 1), so no server, build,
sampling or prompt difference can pass for learning. A reply without token usage raises: Glimmer
tokens are a reported metric, and a missing count must not read as zero.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from symbiont.egress import Destination, Endpoint, post_json

# Glimmer at "Reasoning strength: low" spent all of 400 tokens thinking on 2 of 10 decisions
# (finish_reason "length", empty content). 1500 leaves room for low reasoning plus a short strategy.
REPLY_MAX_TOKENS = 1500
REPLY_TEMPERATURE = 0.6
REPLY_TIMEOUT_S = 300.0  # a decision at reasoning low measured about 32 s; queued slots add more
REASONING_SYSTEM_MESSAGE = (
    "Reasoning strength: low"  # Muse/Glimmer's documented switch for short thinking
)


class GlimmerReplyError(ValueError):
    """The server's reply lacks a field the episode log reports (for example token usage)."""


@dataclass(frozen=True)
class TokenUsage:
    """Tokens the server counted for one request."""

    prompt: int
    completion: int


@dataclass(frozen=True)
class Reply:
    """What the model said: text, why it stopped, and how much it spent thinking.

    `tokens` is None only for scripted policies, which call no model.
    """

    text: str
    finish_reason: str
    reasoning_chars: int
    tokens: TokenUsage | None = None


ReplyFn = Callable[[str], Reply]


def parse_chat_response(out: dict[str, Any]) -> Reply:
    """Read the reply text, finish reason, size of the hidden reasoning and token usage.

    Raises GlimmerReplyError when the server reports no usage.
    """
    choice = out["choices"][0]
    message = choice["message"]
    usage = out.get("usage")
    if not usage or "prompt_tokens" not in usage or "completion_tokens" not in usage:
        raise GlimmerReplyError("the server reported no token usage for this reply")
    return Reply(
        text=(message.get("content") or "").strip(),
        finish_reason=choice.get("finish_reason") or "unknown",
        reasoning_chars=len(message.get("reasoning_content") or ""),
        tokens=TokenUsage(int(usage["prompt_tokens"]), int(usage["completion_tokens"])),
    )


def chat_reply(
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: float = REPLY_TIMEOUT_S,
    max_tokens: int = REPLY_MAX_TOKENS,
) -> Reply:
    """Ask the local Glimmer server for one reply, through the egress module."""
    return _post_chat(base_url, chat_body(model, prompt, max_tokens), timeout_s)


def chat_body(model: str, prompt: str, max_tokens: int = REPLY_MAX_TOKENS) -> dict[str, Any]:
    """The request every game decision sends: reasoning low, the prompt, the reply budget."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": REASONING_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": REPLY_TEMPERATURE,
    }


def _post_chat(base_url: str, body: dict[str, Any], timeout_s: float) -> Reply:
    # Glimmer is the owner's own server, so no provenance is declared; the egress policy still
    # refuses a public host for this endpoint.
    url = base_url.rstrip("/") + "/chat/completions"
    return parse_chat_response(
        post_json(Destination(Endpoint.LOCAL_GLIMMER, url), body, timeout_s=timeout_s)
    )


@dataclass(frozen=True)
class GlimmerArm:
    """One side of the comparison: the server, the model name and the adapter scales it sends."""

    name: str
    base_url: str
    model: str
    lora_scales: tuple[float, ...] = ()

    def reply(self, prompt: str) -> Reply:
        """One game decision: chat_reply's request plus llama-server's per-request `lora` field.

        No scales sends no field, which is how the production server (no adapters) is asked.
        """
        body = chat_body(self.model, prompt)
        if self.lora_scales:
            body["lora"] = [{"id": i, "scale": scale} for i, scale in enumerate(self.lora_scales)]
        return _post_chat(self.base_url, body, REPLY_TIMEOUT_S)


def plain_and_personal(
    base_url: str, model: str, adapters: int, personal: int
) -> tuple[GlimmerArm, GlimmerArm]:
    """Both arms on one adapter server: plain sends every scale 0, personal sets its adapter to 1.

    Raises ValueError when `personal` is not one of the server's `adapters`.
    """
    if not 0 <= personal < adapters:
        raise ValueError(f"adapter {personal} is not among the server's {adapters}")
    personal_scales = tuple(1.0 if index == personal else 0.0 for index in range(adapters))
    return (
        GlimmerArm("glimmer_plain", base_url, model, (0.0,) * adapters),
        GlimmerArm("glimmer_personal", base_url, model, personal_scales),
    )


def plain_and_personal_by_model(
    base_url: str, plain_model: str, personal_model: str
) -> tuple[GlimmerArm, GlimmerArm]:
    """Each arm names its own served model; the request bodies differ only in `model`.

    The router serves the adapter as a model of its own (`-freedoom`), so no per-request `lora`
    field is sent and no arm can pass for the other through a scale. Raises ValueError when the
    two names are equal, because then both arms would be the same player.
    """
    if plain_model == personal_model:
        raise ValueError(f"both arms would ask the model {plain_model!r}")
    return (
        GlimmerArm("glimmer_plain", base_url, plain_model),
        GlimmerArm("glimmer_personal", base_url, personal_model),
    )
