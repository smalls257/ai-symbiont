"""What a Claude Code read left out, logged by how unusual it is."""

import logging
from collections import Counter
from pathlib import Path

# One logger for the whole Claude Code reader, so a caller filters it by one name.
logger = logging.getLogger("symbiont.readers.claude_code")

# Skips that happen in every session, so one INFO line per file would only bury the unusual ones:
# the harness writes caveat/meta lines, background agents send notifications, and a long session
# is compacted. Any other skip kind names content the reader does not know and logs at INFO.
ROUTINE_SKIPS = frozenset({"caveat or meta line", "task notification", "compaction summary"})
REFUSED_CALLS = "refused tool call"


def report_skips(path: Path, skips: Counter[str]) -> None:
    """Log what the read left out: refused calls as a warning, other skips by how routine."""
    refused = skips.pop(REFUSED_CALLS, 0)
    if refused:
        logger.warning("%s: kept %d malformed tool calls as refused actions", path, refused)
    unusual = {kind: n for kind, n in skips.items() if kind not in ROUTINE_SKIPS}
    routine = {kind: n for kind, n in skips.items() if kind in ROUTINE_SKIPS}
    if unusual:
        logger.info("skipped content in %s: %s", path, unusual)
    if routine:
        logger.debug("skipped routine content in %s: %s", path, routine)
