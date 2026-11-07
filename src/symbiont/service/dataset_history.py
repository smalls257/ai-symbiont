"""Which of a project's sources are datasets (someone else's sessions), not the developer's own.

Why: dataset history is never shown to a session model and its messages are not the developer's
words, so the page must not quote them as "You said". The same rule the summarizer applies.
"""

from symbiont.readers.harnesses import harness_for_reader
from symbiont.store.local import Store


def dataset_readers(store: Store, project: str) -> list[str]:
    """Readers of `project` that are datasets, not a harness; sorted, each once."""
    readers = {s.reader for s in store.sources(project)}
    return sorted(r for r in readers if harness_for_reader(r) is None)
