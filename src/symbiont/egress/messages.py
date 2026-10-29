"""A chat message that carries its own provenance.

Each system, user or tool message declares where it came from, so one private tool observation
cannot ride along under a history-wide declaration. Assistant messages are the model's own
earlier output, derived only from messages that already passed the policy.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from symbiont.egress.policy import EgressRefusedError
from symbiont.records.schema import Provenance

SELF_AUTHORED_ROLES = frozenset({"assistant"})


@dataclass(frozen=True)
class Message:
    """One turn of a history: role, text, where it came from, and wire fields such as tool calls."""

    role: str
    content: str | None
    provenance: tuple[Provenance, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        """The JSON the API takes: provenance stays on this side of the door."""
        return {"role": self.role, "content": self.content, **self.extra}


def declared_provenance(messages: Sequence[Message]) -> list[Provenance]:
    """Every declared record of the history, in order.

    Raises EgressRefusedError (naming the message index and role, never its text) for a system,
    user or tool message that declares none.
    """
    declared: list[Provenance] = []
    for index, message in enumerate(messages):
        if not message.provenance and message.role not in SELF_AUTHORED_ROLES:
            raise EgressRefusedError(
                f"egress refused: message {index} ({message.role}) declares no provenance "
                "(unknown privacy is never shareable)"
            )
        declared.extend(message.provenance)
    return declared
