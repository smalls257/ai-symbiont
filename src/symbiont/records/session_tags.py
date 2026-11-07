"""Record tags that carry what a session was about: Claude Code's title and the git branch.

The reader writes them, the miner reads them as theme text. They live in `records` because the
reader may not import the miner and the miner may not import the reader. A tag is a prefix and a
value, so `tags` stays a flat tuple of strings and old records without them read as before.
"""

TITLE_PREFIX = "ai-title:"
BRANCH_PREFIX = "branch:"
# On an EDIT record whose tool call created the file. The miner must not read a creation as
# rework of an existing file: there was nothing there to rework.
CREATED_TAG = "created"
# On an action record the tool itself rejected (agent input slip). It failed, but it is not a
# mistake worth a pain point: pooled across sessions it would be one meaningless signal.
REFUSED_TAG = "refused"


def title_tag(title: str) -> str:
    """The tag for the session title Claude Code wrote (`ai-title` event)."""
    return TITLE_PREFIX + title


def branch_tag(branch: str) -> str:
    """The tag for the git branch an event was logged on (`gitBranch`)."""
    return BRANCH_PREFIX + branch


def tag_values(tags: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    """The values of the tags that start with `prefix`, in order."""
    return tuple(tag[len(prefix) :] for tag in tags if tag.startswith(prefix))
