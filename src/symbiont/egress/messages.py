"""A chat message that carries its own provenance.

Every message, assistant turns included, declares where it came from, so one private
observation or a replayed private transcript cannot ride along under a history-wide declaration.
An assistant turn takes the provenance of the history it answered (`Message.assistant`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from symbiont.egress.policy import EgressRefusedError
from symbiont.records.schema import Provenance


@dataclass(frozen=True)
class Message:
    """One turn of a history: role, text, where it came from, and wire fields such as tool calls."""

    role: str
    content: str | None
    provenance: tuple[Provenance, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def assistant(
        cls,
        content: str | None,
        history: Sequence["Message"],
        extra: Mapping[str, Any] | None = None,
    ) -> "Message":
        """The model's reply, carrying every record of the history it was derived from."""
        records = tuple(record for message in history for record in message.provenance)
        return cls("assistant", content, records, extra or {})

    def wire(self) -> dict[str, Any]:
        """The JSON the API takes: provenance stays on this side of the door."""
        return {"role": self.role, "content": self.content, **self.extra}


def declared_provenance(messages: Sequence[Message]) -> list[Provenance]:
    """Every declared record of the history, in order.

    Raises EgressRefusedError (naming the message index and role, never its text) for any
    message that declares none.
    """
    declared: list[Provenance] = []
    for index, message in enumerate(messages):
        if not message.provenance:
            raise EgressRefusedError(
                f"egress refused: message {index} ({message.role}) declares no provenance "
                "(unknown privacy is never shareable)"
            )
        declared.extend(message.provenance)
    return declared
