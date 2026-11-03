"""How an operator command reaches the running service, and the two ways that can fail."""

from collections.abc import Callable
from typing import Any

AskService = Callable[[str, dict[str, object], int], dict[str, Any]]


class ServiceUnavailableError(ConnectionError):
    """An `AskService` could not reach the running service; the message says where."""


class ServiceAnswerError(RuntimeError):
    """An `AskService` reached the service but got no usable answer; the message says why."""
