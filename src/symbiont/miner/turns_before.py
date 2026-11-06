"""The turns just before a failure: what the user asked and what the agent said it would do.

A candidate shown without the request it came from cannot be
judged worth keeping, and the developer ends up reading transcripts to find out.
"""

from collections.abc import Sequence

from symbiont.records.schema import Kind, Record

# The same cap as a correction candidate's turn (core/correction_candidates.MAX_TURN_CHARS):
# a citation of the request, not a copy of the conversation. Kept in step by a test.
CONTEXT_CHARS = 280
_OUR_OUTPUT = "symbiont-output"


def last_turn_before(records: Sequence[Record], step: int, kind: Kind) -> Record | None:
    """The nearest record of `kind` before `step` in this session; None at the session start.

    Text our own delivery added is skipped: it is not something the user or the agent said.
    """
    earlier = [rec for rec in records if rec.step < step and rec.kind is kind]
    earlier = [rec for rec in earlier if _OUR_OUTPUT not in rec.tags]
    return max(earlier, key=lambda rec: rec.step, default=None)
