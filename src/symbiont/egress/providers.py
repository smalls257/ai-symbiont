"""The remote chat providers a payload may be sent to: the one place a new host is added.

REMOTE_HOSTS derives from this code table; a host read from settings or the environment would
make the egress door configurable at run time, so none is. `policy.py` imports it from here
(the table sits below the policy) and `remote_chat.py` re-exports it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnknownProviderError(LookupError):
    """A provider name that is not in the table; the message lists the known ones."""


@dataclass(frozen=True)
class RemoteProvider:
    """One remote chat API: its name here, the only host it may reach and its chat URL."""

    name: str
    host: str
    chat_url: str

    def __post_init__(self) -> None:
        """Refuse an entry whose chat URL is not https on its own host."""
        parts = urlsplit(self.chat_url)
        if parts.scheme != "https" or (parts.hostname or "").lower() != self.host:
            raise ValueError(
                f"provider {self.name!r}: chat_url must be an https URL on host {self.host!r}"
            )


# Muse Spark's OpenAI-compatible chat API. A new model API is a new entry here plus a policy test.
PROVIDERS: Mapping[str, RemoteProvider] = {
    "meta": RemoteProvider("meta", "api.meta.ai", "https://api.meta.ai/v1/chat/completions"),
}


def provider(name: str) -> RemoteProvider:
    """The provider called `name`; raises UnknownProviderError naming the known ones."""
    try:
        return PROVIDERS[name]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise UnknownProviderError(f"unknown provider {name!r}; known providers: {known}") from None
