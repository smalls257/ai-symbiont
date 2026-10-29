"""Route B training rows for the Freedoom adapter: game lessons as chat rows Glimmer reads (pure).

Same row shape as scripts/routeb (`{"messages": [system, user, assistant]}`), under the system turn
the game loop sends, so the adapter trains on the prompt it plays under. Each lesson gives two card
rows (asked for the lesson, asked for the check) and, when the decision log holds the resolving
decision, one situation row: the exact game prompt at that decision and the move lines that got
past the mistake.

Violation prevented: Paper Tiger. An adapter trained only on question-and-answer cards can recall a
lesson when asked and still play the same way, because nobody asks during play; the situation row
puts the lesson where play happens. Violation prevented: Silent Fallback at the hold-out boundary:
a lesson from a held-out level raises `HeldOutLevelError` instead of being skipped.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from symbiont.act1.game_lessons import GameLesson
from symbiont.act1.glimmer import REASONING_SYSTEM_MESSAGE
from symbiont.act1.levels import require_training

Row = dict[str, list[dict[str, str]]]


@dataclass(frozen=True)
class Situation:
    """The game prompt the loop sent at one decision, and the reply whose moves were played."""

    prompt: str
    reply: str


def select_lessons(
    lessons: Iterable[GameLesson], count: int, per_check: int
) -> tuple[GameLesson, ...]:
    """Up to `count` lessons: repeated mistakes first, no two cards alike.

    At most `per_check` lessons teach the same check, so one habit cannot fill the set. Ties keep
    history order (the sort is stable). Raises HeldOutLevelError for a held-out level's lesson.
    """
    ranked = sorted(lessons, key=lambda lesson: -lesson.repeats)
    chosen: list[GameLesson] = []
    cards: set[str] = set()
    checks: Counter[str] = Counter()
    for lesson in ranked:
        require_training(lesson.level)
        if lesson.card() in cards or checks[lesson.check] >= per_check:
            continue
        cards.add(lesson.card())
        checks[lesson.check] += 1
        chosen.append(lesson)
        if len(chosen) == count:
            break
    return tuple(chosen)


def training_rows(lesson: GameLesson, situation: Situation | None) -> list[Row]:
    """Two card rows, plus the situation row when the resolving decision was logged."""
    require_training(lesson.level)
    rows = [
        _chat(
            f"What is the lesson from {_where(lesson)}: what happened, how was it resolved, "
            "and what should I check?",
            lesson.card(),
        ),
        _chat(f"{lesson.what_happened} What should you check next time?", lesson.check),
    ]
    if situation is not None:
        rows.append(_chat(situation.prompt, situation.reply))
    return rows


def dataset_rows(
    lessons: Sequence[GameLesson], situations: dict[tuple[str, int], Situation]
) -> list[Row]:
    """Rows for every lesson, in lesson order; a situation is looked up by (session, decision)."""
    return [
        row
        for lesson in lessons
        for row in training_rows(lesson, situations.get((lesson.session_id, lesson.resolved_at)))
    ]


def _where(lesson: GameLesson) -> str:
    return f"Freedoom {lesson.level} ({lesson.pain.value.replace('_', ' ')})"


def _chat(question: str, answer: str) -> Row:
    return {
        "messages": [
            {"role": "system", "content": REASONING_SYSTEM_MESSAGE},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }
