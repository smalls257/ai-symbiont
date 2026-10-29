"""The Meta API key: loaded from one env file, held where `repr` cannot print it.

Violation prevented: Black Box in reverse, a secret leaking into logs, tracebacks or commits. The
key lives in an object whose repr is redacted, is read only by `load_meta_key` from
`~/.config/symbiont/meta.env` (outside the repo), and reaches the wire only as the Authorization
header `post_json` adds. A missing key raises (Silent Fallback: no unauthenticated send that
would look like a quiet success).
"""

from dataclasses import dataclass
from pathlib import Path

KEY_VARIABLE = "META_API_KEY"
DEFAULT_ENV_FILE = Path.home() / ".config" / "symbiont" / "meta.env"


class MissingCredentialError(RuntimeError):
    """The key file or its variable is absent; the message never contains a value."""


@dataclass(frozen=True)
class ApiKey:
    """A bearer token whose repr and str are redacted; `reveal` is the one way to the value."""

    _value: str

    def reveal(self) -> str:
        """The raw token; called only where the Authorization header is built."""
        return self._value

    def __repr__(self) -> str:
        """Redacted, so a log line, traceback or test failure cannot print the token."""
        return "ApiKey(<redacted>)"

    __str__ = __repr__


def load_meta_key(path: Path = DEFAULT_ENV_FILE) -> ApiKey:
    """Read META_API_KEY from an env file of KEY=VALUE lines. Raises MissingCredentialError."""
    if not path.is_file():
        raise MissingCredentialError(f"{path} does not exist; it must define {KEY_VARIABLE}")
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.strip().partition("=")
        if name == KEY_VARIABLE and value.strip():
            return ApiKey(value.strip().strip("\"'"))
    raise MissingCredentialError(f"{path} does not define {KEY_VARIABLE}")
