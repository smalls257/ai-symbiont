"""Whether a failed command ran a file its own session created.

Every session writes its own `reproduce_issue.py`; grouping by
the name across sessions invents a recurrence. Where a file lives cannot tell scratch from
`manage.py`, so the only honest evidence is the history: an edit that made the file, earlier in
the same session.
"""

from collections.abc import Sequence

from symbiont.miner.codebase import THROWAWAY_DIRS, repo_relative
from symbiont.records.schema import Kind, Record
from symbiont.records.session_tags import CREATED_TAG, REFUSED_TAG


def target_created_before(
    target: str, records: Sequence[Record], step: int, repo_names: frozenset[str]
) -> bool:
    """True when an applied edit tagged `created` on `target` came before `step` in `records`."""
    wanted = _identity(target, repo_names)
    return any(
        wanted == _identity(path, repo_names)
        for record in records
        if record.kind is Kind.EDIT
        and CREATED_TAG in record.tags
        and REFUSED_TAG not in record.tags  # a refused create made no file
        and record.step < step
        for path in record.files
    )


def _identity(path: str, repo_names: frozenset[str]) -> tuple[str, str]:
    """One identity for a file however the session spelled it: path in the repo, else name."""
    inside = repo_relative(path, repo_names)
    if inside is not None:
        return ("repo", inside)
    # Scratch files at the top level or in `/workspace/x/` share only a name; a temporary
    # directory matches only its full path, so `/tmp/manage.py` is not the project's `manage.py`.
    if path.startswith(THROWAWAY_DIRS):
        return ("temporary", path)
    return ("name", path.rsplit("/", 1)[-1])
