"""The names the developer chose for topics and failure groups, told to the session model.

A summary run that renames what the developer already renamed would discard their work without
a word; `topics/candidates` carries each (generated name, chosen name) pair so the model keeps it.
"""

from typing import Any

from symbiont.service.incident_view import incidents_snapshot
from symbiont.store.local import Store

KEEP_NAMES = (
    "The developer renamed some topics and groups (developer_names, was -> now). Keep a name "
    "they chose wherever the same topic or group appears in your map."
)


def developer_names(store: Store, project: str) -> list[dict[str, str]]:
    """Topics first, then groups still present, as {was, now, of}; gone groups are left out."""
    told = [
        {"was": was, "now": now, "of": "topic"}
        for was, now in store.review.summaries.topic_names(project).items()
    ]
    chosen = store.review.triage.names(project)
    if not chosen:
        return told
    groups: list[dict[str, Any]] = incidents_snapshot(store, project)["groups"]
    told += [
        {"was": g["name"], "now": chosen[g["key"]], "of": f"{g['kind']} group"}
        for g in groups
        if g["key"] in chosen
    ]
    return told
