"""Where the failure signature used to live; it moved to `symbiont.miner.failure_signature`.

The miner keys failed commands by the message, and the miner may not import core, so the module
sits below both. This re-export keeps the core's own imports stable.
"""

from symbiont.miner.failure_signature import (
    DETAIL_CHARS,
    FailureSignature,
    failure_detail,
    failure_signature,
    same_failure,
)

__all__ = [
    "DETAIL_CHARS",
    "FailureSignature",
    "failure_detail",
    "failure_signature",
    "same_failure",
]
