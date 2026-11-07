"""What the developer and their session's model decided about the mined history.

Triage, session summaries and group verdict sentences share one accessor on `Store`: all are
developer-owned state that a re-mine keeps, and one accessor keeps `Store` within its public-
method cap.
"""

from dataclasses import dataclass

from symbiont.store.group_verdicts import GroupVerdicts
from symbiont.store.session_summaries import SessionSummaries
from symbiont.store.triage import GroupTriage


@dataclass(frozen=True)
class ReviewState:
    """The developer-owned review state of the store's projects."""

    triage: GroupTriage
    summaries: SessionSummaries
    verdicts: GroupVerdicts
