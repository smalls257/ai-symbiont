"""The words and silences in force for each lesson: the developer's own, over the review verdicts.

A `mistake` verdict's rule follows the developer's words. `expected` and `noise` silence a lesson
only when the developer said nothing about it: any saved context (words, a priority, or an
explicit intentional choice) keeps it active, the verdict stays a suggestion, and the dashboard
shows the conflict. The developer's choice wins.
"""

from symbiont.miner.lesson_context import (
    LessonContext,
    Priority,
    Review,
    ReviewOverride,
    Verdict,
)
from symbiont.store.local import Store


def effective_contexts(store: Store, project: str) -> dict[str, LessonContext]:
    """Lesson id -> the words and silence that apply, reviews merged under the developer's."""
    own = store.contexts.all(project)
    merged = dict(own)
    answers = store.contexts.overrides(project)
    for lesson_id, review in store.curation.reviews(project).items():
        merged[lesson_id] = _merged(own.get(lesson_id), review, answers.get(lesson_id))
    return merged


def _merged(
    own: LessonContext | None, review: Review, answer: ReviewOverride | None
) -> LessonContext:
    """One lesson's words: the developer's first, then the reviewed rule; their choice wins.

    A keep or dismiss answer to the reviewer ends the question: dismiss silences the lesson, keep
    leaves it active, whatever the verdict says.
    """
    priority = own.priority if own else Priority.NORMAL
    silent = own.intentional if own is not None else review.verdict is not Verdict.MISTAKE
    if answer is not None:
        silent = answer is ReviewOverride.DISMISS
    rule = review.rule.strip(" .") if review.verdict is Verdict.MISTAKE else ""
    text = ". ".join(part for part in (own.text.strip(" .") if own else "", rule) if part)
    applies = own.applies if own and (own.applies.terms or own.applies.areas) else review.applies
    return LessonContext(text, silent, priority, applies)
