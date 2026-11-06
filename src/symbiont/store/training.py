"""The two training exports of stored lessons, one per model, as two named functions.

Route A's memory model writes notes that can reach a remote model, so its export goes through
the remote view: one private lesson raises `RemotePrivacyViolationError`, never a shorter list.
Route B's personal model stays local and may learn from every lesson. Lessons a manifest already
lists are not offered to the memory model again.
"""

from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.store.local import Store


def lessons_for_memory_model(
    store: Store, project: str, consent: OwnHistoryConsent = OwnHistoryConsent.WITHHELD
) -> list[Lesson]:
    """Route A: the scrubbed lessons of `project` not yet trained on.

    Raises RemotePrivacyViolationError if any lesson may not reach a remote model under `consent`.
    """
    trained = store.trained_lesson_ids(project)
    allowed = store.remote_view(consent).lessons(project)
    return [lesson for lesson in allowed if lesson_id(lesson) not in trained]


def lessons_for_personal_model(store: Store, project: str) -> list[Lesson]:
    """Route B: every lesson of `project`, private ones included; for local training only."""
    return store.lessons(project)
