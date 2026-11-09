"""Sizes and small words every note shares, so the note modules agree on them."""

# A note is read in passing by the agent; owner: "word vomit" is the failure to avoid.
NOTE_CHARS = 300
# Below this a clause (a "While" or a reviewer's point) says too little to keep.
MIN_WHILE_CHARS = 30


def times(count: int) -> str:
    """`once` or `N times`, for prose."""
    return "once" if count == 1 else f"{count} times"
