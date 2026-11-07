"""Whether a failed command ran a file its own session created.

Every session writes its own `reproduce_issue.py`; grouping by
the name across sessions invents a recurrence. Where a file lives cannot tell scratch from
`manage.py`, so the only honest evidence is the history: an edit that made the file, earlier in
the same session.
"""

from collections.abc import Sequence

from symbiont.miner.codebase import repo_relative
from symbiont.records.schema import Kind, Record
from symbiont.records.session_tags import CREATED_TAG


def target_created_before(
    target: str, records: Sequence[Record], step: int, repo_names: frozenset[str]
) -> bool:
    """True when an edit tagged `created` on `target` came before `step` in `records`."""
    wanted = _identity(target, repo_names)
    return any(
        wanted == _identity(path, repo_names)
        for record in records
        if record.kind is Kind.EDIT and CREATED_TAG in record.tags and record.step < step
        for path in record.files
    )


def _identity(path: str, repo_names: frozenset[str]) -> str:
    """One name for a file however the session spelled it: repo-relative, else its file name.

    Scratch files sit outside the codebase's own rule (top level, `/workspace/x/`), where the
    file name is all `./f.py`, `f.py` and `/workspace/x/f.py` share.
    """
    return repo_relative(path, repo_names) or path.rsplit("/", 1)[-1]
