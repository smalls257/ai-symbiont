"""Our own output inside a session log.

The delivery layer appends notes, recall answers and offline notes to tool
output, each introduced by a line that is exactly `OUR_OUTPUT_TAG`. Readers cut
that part off and tag the record, so the miner never learns from what we said.
"""

OUR_OUTPUT_TAG = "[symbiont]"
OUR_OUTPUT_RECORD_TAG = "symbiont-output"


def is_our_output(text: str) -> bool:
    """True when some line of `text` is exactly the tag."""
    return _tag_offset(text) is not None


def split_our_output(text: str) -> tuple[str, str]:
    """Return (the harness's own text, our part from the tag line on)."""
    offset = _tag_offset(text)
    if offset is None:
        return text, ""
    return text[:offset], text[offset:]


def _tag_offset(text: str) -> int | None:
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n") == OUR_OUTPUT_TAG:
            return offset
        offset += len(line)
    return None
