"""Which repository a lesson id belongs to, whether it was mined or written."""

from symbiont.store.local import Store


def project_of_lesson(store: Store, ident: str) -> str | None:
    """The repository of the mined or written lesson `ident`, or None when no lesson has it."""
    mined = store.catalog.find(ident)
    if mined is not None:
        return mined[0]
    written = store.curation.find_authored(ident)
    return None if written is None else written[0]
