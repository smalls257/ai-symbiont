"""The stated-rule candidates still waiting for the session model, shaped for it.

Candidates come in as arguments (mined by `miner`, read through the store), so this is pure
over them. Only candidates from sessions the running harness may read are offered, and none
that a saved rule or a drop already covers.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol

MAX_RULE_CANDIDATES = 80


class CandidateLike(Protocol):
    """What the offer needs from a mined candidate; the mined type has more."""

    @property
    def session_id(self) -> str:
        """The session the developer said it in."""
        ...

    @property
    def step(self) -> int:
        """The step of that message."""
        ...

    @property
    def text(self) -> str:
        """The message, already scrubbed and capped."""
        ...


def waiting_candidates(
    candidates: Sequence[CandidateLike],
    readable: Collection[str],
    covered: Collection[tuple[str, int]],
) -> list[CandidateLike]:
    """Readable candidates no rule or drop covers, oldest session first."""
    return [
        c for c in candidates if c.session_id in readable and (c.session_id, c.step) not in covered
    ]


def offered(
    waiting: Sequence[CandidateLike], dates: Mapping[str, str | None]
) -> tuple[list[dict[str, Any]], int]:
    """Up to 80 candidates as the model reads them, and how many more wait."""
    batch = list(waiting)[:MAX_RULE_CANDIDATES]
    shown = [
        {
            "ref": [c.session_id, c.step],
            "text": c.text,
            "date": dates.get(c.session_id) or "date unknown",
        }
        for c in batch
    ]
    return shown, len(waiting) - len(batch)
