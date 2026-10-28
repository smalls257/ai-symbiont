"""The memory model client: one prompt to a loopback mlx_lm.server, one validated line back.

Violations this shape prevents: Silent Fallback (an unreachable server, a malformed reply or a
line outside the three-part form raises `MemoryModelOfflineError`; the hook then prints
"symbiont offline", never an empty or made-up note) and Distributed Monolith (the call goes
through `symbiont.egress.post_json`, the one door out, to a loopback-only endpoint).

Which model and adapter answer is the server's configuration (`scripts/routea/serve_memory.sh`),
so switching from the stand-in to Llama is a launch argument, not a code change.
"""

import time
from dataclasses import dataclass
from typing import Any

from symbiont.core.memory_note import SYSTEM, InvalidNoteError, note_line
from symbiont.egress import Destination, EgressRefusedError, Endpoint, post_json
from symbiont.egress.client import Transport

# Owner decision 2026-10-28: the ungated MLX copy of Llama 3.2 1B Instruct ("Built with Llama").
DEFAULT_MEMORY_MODEL = "mlx-community/Llama-3.2-1B-Instruct-bf16"
# The ungated stand-in LCAP used; small enough for fast pipeline checks.
STAND_IN_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-bf16"
# mlx_lm.server answers this name with the model and adapter it was launched with.
SERVER_DEFAULT = "default_model"
# One three-part line fits in well under this; greedy decoding keeps notes repeatable.
MAX_TOKENS = 160
# Under the hook client's 10 s, so a slow model is reported as offline by the service itself.
TIMEOUT_S = 8.0


class MemoryModelOfflineError(ConnectionError):
    """No usable note: the server is unreachable, refused, or replied outside the form."""


@dataclass(frozen=True)
class MemoryReply:
    """A validated line and what it cost: sizes and milliseconds, for the event log."""

    line: str
    prompt_chars: int
    elapsed_ms: float


@dataclass(frozen=True)
class MemoryModel:
    """A loopback memory-model server and the projects its adapter learned."""

    url: str
    projects: frozenset[str]
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None

    def knows(self, project: str) -> bool:
        """Whether the adapter was trained on this project's lessons."""
        return project in self.projects

    def write_line(self, prompt: str) -> MemoryReply:
        """The model's one-line note for `prompt`; raises MemoryModelOfflineError, never blanks."""
        started = time.monotonic()
        reply = self._post(prompt)
        try:
            line = note_line(_reply_text(reply))
        except InvalidNoteError as invalid:
            raise MemoryModelOfflineError(f"memory model reply unusable: {invalid}") from invalid
        return MemoryReply(line, len(prompt), (time.monotonic() - started) * 1000.0)

    def _post(self, prompt: str) -> dict[str, Any]:
        destination = Destination(
            Endpoint.LOCAL_MEMORY_MODEL, self.url.rstrip("/") + "/v1/chat/completions"
        )
        try:
            if self.transport is None:
                return post_json(destination, _request(prompt), timeout_s=TIMEOUT_S)
            return post_json(
                destination, _request(prompt), timeout_s=TIMEOUT_S, transport=self.transport
            )
        except EgressRefusedError:
            raise
        except (OSError, ValueError) as failed:
            reason = type(failed).__name__
            raise MemoryModelOfflineError(
                f"memory model at {self.url} failed: {reason}"
            ) from failed


def _request(prompt: str) -> dict[str, object]:
    return {
        "model": SERVER_DEFAULT,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
        "stop": ["\n"],
    }


def _reply_text(reply: dict[str, Any]) -> str:
    try:
        text = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as missing:
        raise InvalidNoteError("the reply has no choices[0].message.content") from missing
    if not isinstance(text, str):
        raise InvalidNoteError("the reply's content is not text")
    return text
