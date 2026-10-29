"""Training rows for a lesson card, the same shape in every domain (pure).

The card row comes first, because a down-weighted lesson keeps only its first row. An open card
gets no "what worked?" row: there is nothing verified to say. Verify questions use a wording no
training row uses, so the install check measures the lesson, not the prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from loop_cards import LessonCard
from training_plan import Row

VERIFY_QUESTIONS = 3  # verify_glimmer_models.py asks at most three per path


def _chat(system: str, question: str, answer: str) -> tuple[dict[str, str], ...]:
    return (
        {"role": "system", "content": system},
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    )


def card_rows(card: LessonCard, system: str, subject: str) -> list[Row]:
    """Card, then resolution (closed cards only), then check, under the domain's memory turn."""
    about = card.situation.rstrip(".")
    asked = [("card", f"{subject}: {about}. What have you learned?", card.text())]
    if not card.is_open:
        asked.append(("resolved", f"{subject}: {about}. What worked?", card.how_resolved))
    asked.append(("check", f"{subject}: {about}. Which check do you run?", card.check))
    return [Row(card.lesson_id, kind, _chat(system, q, a)) for kind, q, a in asked]


def verify_questions(cards: Sequence[LessonCard], subject: str) -> list[dict[str, str]]:
    """Up to VERIFY_QUESTIONS held-out wordings, in the shape verify_glimmer_models.py reads."""
    return [
        {
            "question_id": f"{card.lesson_id}-q",
            "lesson_id": card.lesson_id,
            "text": f"{subject}, before you go on when {card.situation.rstrip('.').lower()}: "
            "what should you remember?",
        }
        for card in cards[:VERIFY_QUESTIONS]
    ]
