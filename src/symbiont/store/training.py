"""The two training exports of stored lessons, one per model, as two named functions.

Route A's memory model writes notes that can reach Spark-bound prompts, so its
export goes through the fail-closed Spark view: one private lesson in the
project raises `SparkPrivacyViolationError`, never a quietly shorter list.
Route B's personal model (local Glimmer) never leaves the machine and may learn
from every lesson, private ones included. Lessons a manifest already lists
(trained on, then recreated by re-mining) are not offered to the memory model.
"""

from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id
from symbiont.records.privacy import OwnHistoryConsent
from symbiont.store.local import Store


def lessons_for_memory_model(
    store: Store, project: str, consent: OwnHistoryConsent = OwnHistoryConsent.WITHHELD
) -> list[Lesson]:
    """Route A: the scrubbed lessons of `project` not yet trained on.

    Raises SparkPrivacyViolationError if any lesson may not reach Spark under `consent`
    (any private lesson without consent; a third-party one always). Re-mining recreates
    lessons a manifest already lists; they are not offered again.
    """
    trained = store.trained_lesson_ids(project)
    allowed = store.spark_view(consent).lessons(project)
    return [lesson for lesson in allowed if lesson_id(lesson) not in trained]


def lessons_for_personal_model(store: Store, project: str) -> list[Lesson]:
    """Route B: every lesson of `project`, private ones included; for local training only."""
    return store.lessons(project)
