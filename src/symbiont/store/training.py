"""The two training exports of stored lessons, one per model, as two named functions.

Route A's memory model writes notes that can reach Spark-bound prompts, so its
export goes through the fail-closed Spark view: one private lesson in the
project raises `SparkPrivacyViolationError`, never a quietly shorter list.
Route B's personal model (local Glimmer) never leaves the machine and may learn
from every lesson, private ones included.
"""

from symbiont.miner.lessons import Lesson
from symbiont.store.local import Store


def lessons_for_memory_model(store: Store, project: str) -> list[Lesson]:
    """Route A: every lesson of `project`, or SparkPrivacyViolationError if any is private."""
    return store.spark_view().lessons(project)


def lessons_for_personal_model(store: Store, project: str) -> list[Lesson]:
    """Route B: every lesson of `project`, private ones included; for local training only."""
    return store.lessons(project)
