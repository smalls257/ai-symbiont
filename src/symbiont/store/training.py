"""The two training exports of stored lessons, one per model, as two named functions.

Route A's memory model writes notes that can reach Spark, so its export goes through the Spark
view: one private lesson raises `SparkPrivacyViolationError`, never a shorter list. Route B's
personal model stays local and may learn from every lesson. Lessons a manifest already lists are
not offered to the memory model again.
"""

from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id
from symbiont.store.local import Store


def lessons_for_memory_model(store: Store, project: str) -> list[Lesson]:
    """Route A: the lessons of `project` not yet trained on; raises if any lesson is private.

    Re-mining recreates lessons a manifest already lists; they are not offered again.
    """
    trained = store.trained_lesson_ids(project)
    return [
        lesson for lesson in store.spark_view().lessons(project) if lesson_id(lesson) not in trained
    ]


def lessons_for_personal_model(store: Store, project: str) -> list[Lesson]:
    """Route B: every lesson of `project`, private ones included; for local training only."""
    return store.lessons(project)
