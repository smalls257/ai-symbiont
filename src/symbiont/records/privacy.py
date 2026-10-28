"""Whose history a record is, and whether its owner consented to it reaching Spark.

The owner may consent to their OWN sessions reaching Spark (owner decision 2026-10-28): an
explicit setting, default withheld, never covering someone else's private data. A dataset not
named here as the user's own is third-party.
"""

from enum import StrEnum

# Records the hooks write from a live session: "live-<harness>" (delivery/hooks.py).
LIVE_DATASET_PREFIX = "live-"
# The user's own harness logs, as the readers label them (readers/claude_code.py).
OWN_HISTORY_DATASETS = frozenset({"private-sessions"})


class OwnHistoryConsent(StrEnum):
    """Whether the user lets lessons from their own sessions reach Spark."""

    WITHHELD = "withheld"
    GIVEN = "consent"


def is_own_history(dataset: str) -> bool:
    """True for the user's own sessions; every other private dataset is third-party."""
    return dataset in OWN_HISTORY_DATASETS or dataset.startswith(LIVE_DATASET_PREFIX)
