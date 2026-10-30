"""Every pain-point signal, in one call.

The store and the wizard call this rather than each signal, so adding a
signal is one line here and nothing changes downstream.

A chain is a developer's sessions on one repo in the order they ran. Most
signals look inside one session; reworked edits also look across the chain
(Tuesday's session takes out what Monday's put in). Parallel attempts at the
same task are not a chain: pass each as a chain of one.
"""

from collections.abc import Mapping, Sequence

from symbiont.miner.painpoint import PainPoint
from symbiont.miner.signals.blast_radius import find_blast_radius
from symbiont.miner.signals.correction import find_corrections
from symbiont.miner.signals.failed_command import find_failed_commands
from symbiont.miner.signals.loop import find_loops
from symbiont.miner.signals.review_flag import find_review_flags
from symbiont.miner.signals.reworked_edit import find_reworked_edits
from symbiont.records.schema import Record

References = Mapping[str, frozenset[str]]


def mine_chain(sessions: Sequence[Sequence[Record]], references: References) -> list[PainPoint]:
    """Mine `sessions`, given in the order they ran.

    `references[path]` = files that import or name `path` (see blast_radius); `{}`
    when there is no repo checkout, and blast radius then finds nothing.
    """
    found = [p for session in sessions for p in _within_session(session, references)]
    found += find_reworked_edits([record for session in sessions for record in session])
    return found


def mine_session(session: Sequence[Record], references: References) -> list[PainPoint]:
    """Mine one session as a chain of one (parallel attempts are not a chain)."""
    return mine_chain([session], references)


def _within_session(session: Sequence[Record], references: References) -> list[PainPoint]:
    return [
        *find_failed_commands(session),
        *find_loops(session),
        *find_blast_radius(session, references),
        *find_corrections(session),
        *find_review_flags(session),
    ]
